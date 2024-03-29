from collections import Counter, defaultdict
from datetime import timedelta
import operator
from typing import Literal

from django import forms
from django.conf import settings
from django.db import models
from django.db.models.lookups import LessThan
from django.db.models.expressions import Case, F, Value, When
from django.utils import timezone

from images.models import Source
from lib.forms import BoxFormRenderer
from .models import Job


class BaseJobForm(forms.Form):
    source_id: int | None | Literal['all']

    @property
    def show_source_check_jobs(self):
        raise NotImplementedError

    @property
    def status_filter(self):
        raise NotImplementedError

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

        if self.source_id is None:
            # Non-source jobs only.
            jobs = jobs.filter(source__isnull=True)
        elif self.source_id != 'all':
            # One source only.
            jobs = jobs.filter(source_id=self.source_id)
        # Else, all sources.

        if not self.show_source_check_jobs:
            jobs = jobs.exclude(job_name='check_source')

        status_filter = self.status_filter
        if status_filter == 'completed':
            status_kwargs = dict(
                status__in=[Job.Status.SUCCESS, Job.Status.FAILURE])
        elif status_filter:
            status_kwargs = dict(status=status_filter)
        else:
            status_kwargs = dict()
        jobs = jobs.filter(**status_kwargs)

        sort_method = self.job_sort_method
        if sort_method == 'status':
            # In-progress jobs first, then pending + due,
            # then pending + scheduled for later, then completed.
            # Tiebreak by last updated, then by ID (last created).
            jobs = jobs.annotate(
                due=LessThan(F('scheduled_start_date'), timezone.now()),
                status_score=Case(
                    When(status=Job.Status.IN_PROGRESS, then=Value(1)),
                    When(status=Job.Status.PENDING, due=True, then=Value(2)),
                    When(status=Job.Status.PENDING, due=False, then=Value(3)),
                    When(status=Job.Status.PENDING, due=None, then=Value(4)),
                    default=Value(5),
                    output_field=models.fields.IntegerField(),
                )
            )
            jobs = jobs.order_by('status_score', '-modify_date', '-id')
        elif sort_method == 'recently_updated':
            jobs = jobs.order_by('-modify_date', '-id')
        else:
            # 'recently_created'
            jobs = jobs.order_by('-id')

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
            ('recently_created', "Recently created"),
        ],
        required=False, initial='status',
    )
    # show_source_check_jobs: See __init__()

    default_renderer = BoxFormRenderer

    def __init__(self, *args, **kwargs):
        self.source_id: int | None | Literal['all'] = kwargs.pop('source_id')
        super().__init__(*args, **kwargs)

        # check_source jobs often clutter the job list more than they provide
        # useful info. So they're hidden by default, but there's an option
        # to show them.
        if self.source_id is None:
            # Non-source jobs only, so source check jobs cannot be included.
            # Don't need to display the show source check jobs field.
            self.fields['show_source_check_jobs'] = forms.BooleanField(
                widget=forms.HiddenInput(),
                required=False, initial=False,
            )
        else:
            self.fields['show_source_check_jobs'] = forms.BooleanField(
                label="Show source-check jobs",
                required=False, initial=False,
            )

    @property
    def show_source_check_jobs(self):
        return self.get_field_value('show_source_check_jobs')

    @property
    def status_filter(self):
        return self.get_field_value('status')

    @property
    def job_sort_method(self):
        return self.get_field_value('sort')

    @property
    def completed_day_limit(self):
        return settings.JOB_MAX_DAYS


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

    source_id = 'all'
    default_renderer = BoxFormRenderer

    @property
    def show_source_check_jobs(self):
        return False

    @property
    def status_filter(self):
        return ''

    @property
    def job_sort_method(self):
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
