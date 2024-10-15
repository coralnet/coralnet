from collections import Counter, defaultdict
import datetime
from datetime import timedelta
import operator

from django import forms
from django.conf import settings
from django.db import models
from django.db.models.expressions import Case, F, When
from django.utils import timezone

from lib.forms import BoxFormRenderer, InlineFormRenderer
from sources.models import Source
from .models import Job
from .utils import (
    get_job_details,
    get_job_names_by_task_queue,
    get_non_source_job_names,
    get_source_job_names,
)


class BaseJobForm(forms.Form):

    @property
    def job_sort_method(self):
        raise NotImplementedError

    @property
    def completed_day_limit(self):
        raise NotImplementedError

    def get_field_value(self, field_name):
        """
        Sometimes we want the field value regardless of whether the
        form was submitted or is in its initial state.
        """
        if self.is_bound:
            return self.cleaned_data[field_name] or self[field_name].initial
        else:
            return self[field_name].initial

    def get_jobs(self):
        if self.is_bound and not self.is_valid():
            return Job.objects.none()

        jobs = Job.objects.all()

        jobs = self._filter_jobs(jobs)
        jobs = self._sort_jobs(jobs)

        return jobs

    def _filter_jobs(self, jobs):
        return jobs

    def _sort_jobs(self, jobs):
        sort_method = self.job_sort_method
        if sort_method == 'status':
            # Incomplete jobs by scheduled start date first.
            # Then completed jobs by last modified.
            # Tiebreak by ID (last created).
            jobs = jobs.annotate(
                incomplete_scheduled_date=Case(
                    # For incomplete jobs with a scheduled start time.
                    When(
                        status__in=[Job.Status.PENDING, Job.Status.IN_PROGRESS],
                        scheduled_start_date__isnull=False,
                        then=F('scheduled_start_date'),
                    ),
                    # For incomplete jobs without a scheduled start time.
                    # Basically this'll always be a later value than any
                    # scheduled start date, and always earlier than the
                    # completed-jobs case.
                    When(
                        status__in=[Job.Status.PENDING, Job.Status.IN_PROGRESS],
                        then=datetime.datetime(
                            year=datetime.MAXYEAR, month=12, day=30,
                            tzinfo=datetime.timezone.utc),
                    ),
                    # For completed jobs.
                    default=datetime.datetime(
                        year=datetime.MAXYEAR, month=12, day=31,
                        tzinfo=datetime.timezone.utc),
                    output_field=models.fields.DateTimeField(),
                ),
            )
            jobs = jobs.order_by(
                'incomplete_scheduled_date',
                # This is the ordering for completed jobs (and also the
                # tiebreaker for incomplete jobs).
                '-modify_date', '-id')
        elif sort_method == 'recently_updated':
            jobs = jobs.order_by('-modify_date', '-id')
        else:
            # 'latest_scheduled'
            # If there's no scheduled date, we'll use start date.
            # If neither, we use an impossibly early date.
            jobs = jobs.annotate(
                scheduled_start_or_start_date=Case(
                    When(
                        scheduled_start_date__isnull=False,
                        then=F('scheduled_start_date'),
                    ),
                    When(
                        start_date__isnull=False,
                        then=F('start_date'),
                    ),
                    default=datetime.datetime(
                        year=datetime.MINYEAR, month=1, day=1,
                        tzinfo=datetime.timezone.utc),
                    output_field=models.fields.DateTimeField(),
                ),
            )
            jobs = jobs.order_by('-scheduled_start_or_start_date', '-id')

        return jobs

    def get_jobs_by_status(self):
        now = timezone.now()

        jobs = self.get_jobs()

        return {
            Job.Status.IN_PROGRESS: jobs.filter(status=Job.Status.IN_PROGRESS),
            Job.Status.PENDING: jobs.filter(status=Job.Status.PENDING),
            'completed': jobs.filter(
                status__in=[Job.Status.SUCCESS, Job.Status.FAILURE],
                modify_date__gt=now - timedelta(days=self.completed_day_limit)
            )
        }

    def get_job_counts(self):
        jobs_by_status = self.get_jobs_by_status()
        return {
            status: job_group.count()
            for status, job_group in jobs_by_status.items()
        }


class JobSearchForm(BaseJobForm):
    status = forms.ChoiceField(
        choices=[
            ('', "Any"),
            *Job.Status.choices,
            ('completed', "Completed"),
        ],
        required=False, initial='',
    )
    sort = forms.ChoiceField(
        label="Sort by",
        choices=[
            ('status', "Status (non-completed first)"),
            ('recently_updated', "Recently updated"),
            ('latest_scheduled', "Latest scheduled"),
        ],
        required=False, initial='status',
    )
    show_hidden = forms.BooleanField(
        label="Show hidden jobs",
        required=False, initial=False,
    )

    default_renderer = BoxFormRenderer

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['type'] = forms.ChoiceField(
            choices=self.get_type_choices,
            required=False, initial='',
        )
        self.order_fields(['status', 'type', 'sort', 'show_hidden'])

    def _filter_jobs(self, jobs):
        jobs = super()._filter_jobs(jobs)

        status_filter = self.get_field_value('status')
        if status_filter == 'completed':
            status_kwargs = dict(
                status__in=[Job.Status.SUCCESS, Job.Status.FAILURE])
        elif status_filter:
            status_kwargs = dict(status=status_filter)
        else:
            status_kwargs = dict()
        jobs = jobs.filter(**status_kwargs)

        type_filter = self.get_field_value('type')
        if type_filter.endswith('_queue_types'):
            queue_name = type_filter[:-len('_queue_types')]
            job_names = get_job_names_by_task_queue()[queue_name]
            jobs = jobs.filter(job_name__in=job_names)
        elif type_filter:
            jobs = jobs.filter(job_name=type_filter)

        show_hidden = self.get_field_value('show_hidden')
        if not show_hidden:
            jobs = jobs.filter(hidden=False)

        return jobs

    @staticmethod
    def get_types():
        raise NotImplementedError

    def get_type_choices(self):
        choices = [('', "Any")]
        for name in self.get_types():
            display_name = get_job_details(name)['display_name']
            choices.append((name, display_name))
        choices.sort(key=operator.itemgetter(1))
        return choices

    @property
    def job_sort_method(self):
        return self.get_field_value('sort')

    @property
    def completed_day_limit(self):
        return settings.JOB_MAX_DAYS


class SourceJobSearchForm(JobSearchForm):
    def __init__(self, *args, **kwargs):
        self.source_id: int = kwargs.pop('source_id')
        super().__init__(*args, **kwargs)

    def _filter_jobs(self, jobs):
        jobs = jobs.filter(source_id=self.source_id)

        return super()._filter_jobs(jobs)

    @staticmethod
    def get_types():
        return get_source_job_names()


class AllJobSearchForm(JobSearchForm):

    @staticmethod
    def get_types():
        return get_source_job_names() + get_non_source_job_names()

    def get_type_choices(self):
        choices = [('', "Any")]
        for name in self.get_types():
            display_name = get_job_details(name)['display_name']
            choices.append((name, display_name))
        for queue_name in settings.DJANGO_HUEY['queues'].keys():
            choices.append(
                (f'{queue_name}_queue_types', f"Any {queue_name} job"))
        choices.sort(key=operator.itemgetter(1))
        return choices


class NonSourceJobSearchForm(JobSearchForm):

    def _filter_jobs(self, jobs):
        jobs = jobs.filter(source__isnull=True)
        return super()._filter_jobs(jobs)

    @staticmethod
    def get_types():
        return get_non_source_job_names()

    def get_type_choices(self):
        choices = [('', "Any")]
        for name in self.get_types():
            display_name = get_job_details(name)['display_name']
            choices.append((name, display_name))
        for queue_name in settings.DJANGO_HUEY['queues'].keys():
            choices.append(
                (f'{queue_name}_queue_types', f"Any {queue_name} job"))
        choices.sort(key=operator.itemgetter(1))
        return choices


class JobSummaryForm(BaseJobForm):
    completed_count_day_limit = forms.IntegerField(
        label="Count completed jobs from this many days back",
        min_value=1, max_value=settings.JOB_MAX_DAYS,
        required=False, initial=3,
    )
    source_sort_method = forms.ChoiceField(
        label="Sort sources by",
        choices=[
            ('job_count', "Job count (in-progress, pending, then completed)"),
            ('recently_updated', "Recently updated jobs"),
            ('source', "Source name"),
        ],
        required=False, initial='job_count',
    )

    default_renderer = BoxFormRenderer

    @property
    def job_sort_method(self):
        # This actually has a purpose near the end of
        # get_job_counts_by_source().
        return 'recently_updated'

    @property
    def completed_day_limit(self):
        return self.get_field_value('completed_count_day_limit')

    def get_job_counts_by_source(self):
        jobs_by_status = self.get_jobs_by_status()

        job_counts_by_source: dict[str | None, dict] = defaultdict(dict)

        for status_tag, job_group in jobs_by_status.items():
            job_source_ids = job_group.values_list('source_id', flat=True)
            source_id_counts = Counter(job_source_ids)
            for source_id, count in source_id_counts.items():
                job_counts_by_source[source_id][status_tag] = count

        non_source_job_counts = job_counts_by_source.pop(None, dict())

        source_ids = list(job_counts_by_source.keys())
        sources = Source.objects.filter(pk__in=source_ids)
        source_names = {
            d['pk']: d['name']
            for d in sources.values('pk', 'name')
        }

        source_entries = []
        for source_id, job_status_counts in job_counts_by_source.items():
            source_entry = job_status_counts
            source_entry['source_id'] = source_id
            source_entry['source_name'] = source_names[source_id]
            source_entries.append(source_entry)

        sort_method = self.get_field_value('source_sort_method')
        if sort_method == 'job_count':
            # Most in-progress jobs first, then tiebreak by most pending
            # jobs, then tiebreak by most completed jobs
            def sort(entry):
                return (
                    entry.get(Job.Status.IN_PROGRESS, 0),
                    entry.get(Job.Status.PENDING, 0),
                    entry.get('completed', 0),
                )
            source_entries.sort(key=sort, reverse=True)
        elif sort_method == 'source':
            source_entries.sort(key=operator.itemgetter('source_name'))
        # Else: 'recently_updated', which the sources should already be sorted
        # by, since the source entries were added while jobs were iterated over
        # in recently-updated-first order.

        return source_entries, non_source_job_counts


class BackgroundJobStatusForm(forms.Form):
    recency_threshold = forms.ChoiceField(
        label="Look at jobs from the past",
        choices=[
            ('1', "hour"),
            ('4', "4 hours"),
            ('24', "day"),
            ('72', "3 days"),
            ('168', "week"),
            ('720', "30 days"),
        ],
        initial='72',
    )

    default_renderer = InlineFormRenderer
