from abc import ABC, abstractmethod
import datetime

from django.conf import settings
from django.contrib.auth.decorators import (
    login_required, permission_required)
from django.db.models import F
from django.shortcuts import get_object_or_404, render
from django.utils.decorators import method_decorator
from django.utils import timezone
from django.views import View

from lib.templatetags.common_tags import timedelta_display
from lib.decorators import source_permission_required
from lib.utils import paginate
from sources.models import Source
from .exceptions import UnrecognizedJobNameError
from .forms import (
    AllJobSearchForm,
    BackgroundJobStatusForm,
    JobSearchForm,
    JobSummaryForm,
    NonSourceJobSearchForm,
    SourceJobSearchForm,
)
from .models import Job
from .utils import (
    get_job_details,
    get_job_names_by_task_queue,
    Time10Percentile,
    Time90Percentile,
)


class JobListView(View, ABC):
    template_name: str
    form: JobSearchForm = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.now = timezone.now()
        self._jobs = None

    def get(self, request, **kwargs):
        context = dict()

        if request.GET:
            self.form = self.get_form(request.GET)
            if not self.form.is_valid():
                context['search_error'] = "Search parameters were invalid."
        else:
            self.form = self.get_form()

        context['job_search_form'] = self.form
        context |= self.get_context(request)

        return render(request, self.template_name, context)

    @abstractmethod
    def get_form(self, data=None):
        raise NotImplementedError

    @property
    def jobs(self):
        if self._jobs is None:
            self._jobs = self.form.get_jobs()
        return self._jobs

    @abstractmethod
    def get_context(self, request):
        raise NotImplementedError

    @property
    @abstractmethod
    def has_source_column(self):
        raise NotImplementedError

    def get_job_list_context(self, request):
        page_jobs = paginate(
            results=self.jobs,
            items_per_page=settings.JOBS_PER_PAGE,
            request_args=request.GET,
        )

        job_table = []

        fields = [
            'pk', 'job_name', 'arg_identifier',
            'apijobunit', 'apijobunit__parent',
            'status', 'result_message',
            'persist', 'hidden',
            'create_date', 'modify_date',
            'scheduled_start_date', 'start_date',
        ]
        if self.has_source_column:
            fields += ['source', 'source__name']

        status_choices_labels = dict(Job.Status.choices)

        for values in page_jobs.object_list.values(*fields):
            job_entry = dict(
                id=values['pk'],
                status=values['status'],
                status_display=status_choices_labels[values['status']],
                result_message=values['result_message'],
                persist=values['persist'],
                hidden=values['hidden'],
                create_date=values['create_date'],
                modify_date=values['modify_date'],
                scheduled_start_date=values['scheduled_start_date'],
                start_date=values['start_date'],
                scheduled_start_or_start_date=
                    values['scheduled_start_date']
                    if values['scheduled_start_date']
                    else values['start_date'],
            )

            if self.has_source_column:
                job_entry['source_id'] = values['source']
                job_entry['source_name'] = values['source__name']

            try:
                job_entry['job_type'] = get_job_details(
                    values['job_name'])['display_name']
            except UnrecognizedJobNameError:
                # This may be an obsolete job type which has yet to be
                # cleaned up. No big deal, just displaying the raw job name
                # should be reasonable enough in this case.
                job_entry['job_type'] = values['job_name']

            if values['job_name'] == 'classify_image':
                job_entry['api_job_unit_id'] = values['apijobunit']
                job_entry['api_job_id'] = values['apijobunit__parent']
            if values['job_name'] in [
                'extract_features', 'classify_features'
            ]:
                job_entry['image_id'] = values['arg_identifier']

            job_table.append(job_entry)

        return dict(
            page_results=page_jobs,
            job_table=job_table,
            job_max_days=settings.JOB_MAX_DAYS,
            job_counts=self.form.get_job_counts(),
            now=self.now,
        )


@method_decorator(
    permission_required('is_superuser'),
    name='dispatch')
class AllJobsListView(JobListView):
    """List of all jobs: from any source or no source."""
    template_name = 'jobs/all_jobs_list.html'

    def get_form(self, data=None):
        return AllJobSearchForm(data=data)

    def get_context(self, request):
        return self.get_job_list_context(request)

    @property
    def has_source_column(self):
        return True


@method_decorator(
    source_permission_required('source_id', perm=Source.PermTypes.EDIT.code),
    name='dispatch')
class SourceJobListView(JobListView):
    """
    List of jobs from a specific source.
    """
    source_id: int
    template_name = 'jobs/source_job_list.html'

    def dispatch(self, *args, **kwargs):
        self.source_id = self.kwargs['source_id']
        return super().dispatch(*args, **kwargs)

    def get_form(self, data=None):
        return SourceJobSearchForm(data=data, source_id=self.source_id)

    def get_context(self, request):
        source = get_object_or_404(Source, id=self.source_id)
        checks = source.job_set.filter(job_name='check_source')

        try:
            latest_check = checks.completed().latest('pk')
        except Job.DoesNotExist:
            latest_check = None

        try:
            incomplete_check = checks.incomplete().latest('pk')
        except Job.DoesNotExist:
            incomplete_check = None
            # Note that this is not redundant with the form results; the form
            # can be filtered, but this cannot be filtered.
            is_doing_any_job = source.job_set.incomplete().exists()
        else:
            # Don't need to check this
            is_doing_any_job = None

        context = dict(
            source=source,
            latest_check=latest_check,
            incomplete_check=incomplete_check,
            is_doing_any_job=is_doing_any_job,
            JobStatus=Job.Status,
        )
        context |= self.get_job_list_context(request)
        return context

    @property
    def has_source_column(self):
        return False


@method_decorator(
    permission_required('is_superuser'),
    name='dispatch')
class NonSourceJobListView(JobListView):
    """
    List of jobs not belonging to a source.
    """
    template_name = 'jobs/non_source_job_list.html'

    def get_form(self, data=None):
        return NonSourceJobSearchForm(data=data)

    def get_context(self, request):
        return self.get_job_list_context(request)

    @property
    def has_source_column(self):
        return False


@method_decorator(
    permission_required('is_superuser'),
    name='dispatch')
class JobSummaryView(View):
    """
    Top-level dashboard for monitoring jobs, showing job counts by source.
    """
    template_name = 'jobs/all_jobs_summary.html'

    def get(self, request, **kwargs):
        if request.GET:
            summary_form = JobSummaryForm(request.GET)
            if not summary_form.is_valid():
                context = dict(
                    job_summary_form=summary_form,
                    search_error="Search parameters were invalid.")
                return render(request, self.template_name, context)
        else:
            summary_form = JobSummaryForm()

        source_entries, non_source_job_counts = \
            summary_form.get_job_counts_by_source()

        overall_job_counts = summary_form.get_job_counts()

        # Last-activity info
        last_active_job_per_source = (
            Job.objects.order_by('source', '-modify_date')
            .distinct('source')
        )
        last_activity_per_source = {
            value_dict['source']: value_dict['modify_date']
            for value_dict
            in last_active_job_per_source.values('source', 'modify_date')
        }

        for entry in source_entries:
            entry['last_activity'] = \
                last_activity_per_source[entry['source_id']]
        non_source_job_counts['last_activity'] = \
            last_activity_per_source.get(None, None)
        if last_activity_per_source:
            overall_job_counts['last_activity'] = \
                sorted(last_activity_per_source.values(), reverse=True)[0]
        else:
            overall_job_counts['last_activity'] = None

        context = dict(
            job_summary_form=summary_form,
            source_table=source_entries,
            overall_job_counts=overall_job_counts,
            non_source_job_counts=non_source_job_counts,
            completed_day_limit=summary_form.completed_day_limit,
        )

        return render(request, self.template_name, context)


@login_required
def background_job_status(request):
    context = dict()

    background_jobs = Job.objects.filter(
        job_name__in=get_job_names_by_task_queue()['background'])

    field = BackgroundJobStatusForm.declared_fields['recency_threshold']
    threshold_hours = field.initial
    if request.GET:
        form = BackgroundJobStatusForm(request.GET)
        if form.is_valid():
            threshold_hours = form.cleaned_data['recency_threshold']
    else:
        form = BackgroundJobStatusForm()
    context['form'] = form
    recency_threshold = datetime.timedelta(hours=int(threshold_hours))
    context['recency_threshold_str'] = dict(field.choices)[threshold_hours]

    now = timezone.now()

    recent_wait_time_jobs = (
        background_jobs
        .filter(start_date__gt=now-recency_threshold,
                scheduled_start_date__isnull=False)
        .annotate(wait_time=F('start_date')-F('scheduled_start_date'))
        .order_by('wait_time')
    )
    interval = [
        recent_wait_time_jobs.aggregate(Time10Percentile('wait_time'))
        ['wait_time__percentile10'],
        recent_wait_time_jobs.aggregate(Time90Percentile('wait_time'))
        ['wait_time__percentile90'],
    ]
    if interval[0] is None:
        interval = [datetime.timedelta(0), datetime.timedelta(0)]
    context['recent_wait_time_interval'] = interval

    recent_total_time_jobs = (
        background_jobs.completed()
        .filter(modify_date__gt=now-recency_threshold,
                scheduled_start_date__isnull=False)
        .annotate(total_time=F('modify_date')-F('scheduled_start_date'))
        .order_by('total_time')
    )
    interval = [
        recent_total_time_jobs.aggregate(Time10Percentile('total_time'))
        ['total_time__percentile10'],
        recent_total_time_jobs.aggregate(Time90Percentile('total_time'))
        ['total_time__percentile90'],
    ]
    if interval[0] is None:
        interval = [datetime.timedelta(0), datetime.timedelta(0)]
    context['recent_total_time_interval'] = interval

    incomplete_count = background_jobs.incomplete().count()
    context['incomplete_count'] = incomplete_count

    # Graph of number of incomplete jobs over time
    now = timezone.now()
    num_intervals = 6
    interval_length = recency_threshold / num_intervals
    completed_jobs = background_jobs.completed()
    graph_data = [dict(
        x=num_intervals,
        y=incomplete_count,
    )]
    interval_start_timestamp = now
    interval_start_time_ago = datetime.timedelta(0)
    # Since we start at now and want to go backwards, we're building the graph
    # from right to left (with time on x axis).
    for i in reversed(range(num_intervals)):
        interval_end_timestamp = interval_start_timestamp
        interval_end_time_ago = interval_start_time_ago
        interval_start_time_ago = interval_end_time_ago + interval_length
        interval_start_timestamp = now - interval_start_time_ago
        created_this_interval_count = background_jobs.filter(
            create_date__gt=interval_start_timestamp,
            create_date__lt=interval_end_timestamp).count()
        completed_this_interval_count = completed_jobs.filter(
            modify_date__gt=interval_start_timestamp,
            modify_date__lt=interval_end_timestamp).count()
        if interval_end_time_ago == datetime.timedelta(0):
            time_ago_display = "Now"
        else:
            time_ago_display = f"{timedelta_display(interval_end_time_ago)} ago"
        graph_data[-1]['tooltip'] = (
            time_ago_display +
            f"<br><strong>{incomplete_count}</strong> incomplete jobs"
            f"<br>Last {timedelta_display(interval_length)}:"
            f" {completed_this_interval_count} completed,"
            f" {created_this_interval_count} created"
        )
        incomplete_count = (
            incomplete_count
            - created_this_interval_count
            + completed_this_interval_count)
        graph_data.append(dict(
            x=i,
            y=incomplete_count,
        ))
        if i == 0:
            graph_data[-1]['tooltip'] = (
                f"{timedelta_display(interval_start_time_ago)} ago" +
                f"<br><strong>{incomplete_count}</strong> incomplete jobs"
            )

    context['incomplete_count_average'] = round(
        sum([d['y'] for d in graph_data]) / len(graph_data))
    context['incomplete_count_graph_data'] = graph_data

    if request.user.is_superuser:
        earliest_incomplete_scheduled_job = (
            background_jobs.incomplete()
            .order_by('scheduled_start_date')
            .first()
        )
        if earliest_incomplete_scheduled_job is None:
            context['earliest_incomplete_scheduled_date'] = None
        else:
            context['earliest_incomplete_scheduled_date'] = (
                earliest_incomplete_scheduled_job.scheduled_start_date)

    return render(request, 'jobs/background_job_status.html', context)
