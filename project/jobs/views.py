from abc import ABC, abstractmethod

from django.conf import settings
from django.contrib.auth.decorators import permission_required
from django.shortcuts import get_object_or_404, render
from django.utils.decorators import method_decorator
from django.views import View

from images.models import Source
from lib.decorators import source_permission_required
from lib.utils import paginate
from .forms import JobSearchForm, JobSummaryForm
from .models import Job


def tag_to_readable(tag):
    return tag.capitalize().replace('_', ' ')


class JobListView(View, ABC):
    template_name: str
    form: JobSearchForm = None

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

    @abstractmethod
    def get_context(self, request):
        raise NotImplementedError

    @property
    @abstractmethod
    def has_source_column(self):
        raise NotImplementedError

    def get_job_list_context(self, request, jobs, job_counts):
        page_jobs, query_string = paginate(
            results=jobs,
            items_per_page=settings.JOBS_PER_PAGE,
            request_args=request.GET,
        )

        job_table = []

        fields = [
            'pk', 'job_name', 'arg_identifier',
            'apijobunit', 'apijobunit__parent',
            'status', 'result_message',
            'persist', 'create_date', 'modify_date',
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
                create_date=values['create_date'],
                modify_date=values['modify_date'],
                scheduled_start_date=values['scheduled_start_date'],
                start_date=values['start_date'],
            )

            if self.has_source_column:
                job_entry['source_id'] = values['source']
                job_entry['source_name'] = values['source__name']

            if values['job_name'] == 'classify_image':
                job_entry['job_type'] = "Deploy"
            if values['job_name'] == 'classify_features':
                job_entry['job_type'] = "Classify"
            else:
                job_entry['job_type'] = tag_to_readable(values['job_name'])

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
            query_string=query_string,
            job_table=job_table,
            job_max_days=settings.JOB_MAX_DAYS,
            job_counts=job_counts,
        )


@method_decorator(
    permission_required('is_superuser'),
    name='dispatch')
class AllJobsListView(JobListView):
    """List of all jobs: from any source or no source."""
    template_name = 'jobs/all_jobs_list.html'

    def get_form(self, data=None):
        return JobSearchForm(data=data, source_id='all')

    def get_context(self, request):
        return self.get_job_list_context(
            request, self.form.get_jobs(), self.form.get_job_counts()
        )

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
        return JobSearchForm(data=data, source_id=self.source_id)

    def get_context(self, request):
        source = get_object_or_404(Source, id=self.source_id)

        try:
            latest_check = source.job_set.filter(
                job_name='check_source',
                status__in=[
                    Job.Status.SUCCESS,
                    Job.Status.FAILURE,
                    Job.Status.IN_PROGRESS,
                ]
            ).latest('pk')
            check_in_progress = (latest_check.status == Job.Status.IN_PROGRESS)
        except Job.DoesNotExist:
            latest_check = None
            check_in_progress = False

        context = dict(
            source=source,
            latest_check=latest_check,
            check_in_progress=check_in_progress,
        )
        context |= self.get_job_list_context(
            request, self.form.get_jobs(), self.form.get_job_counts()
        )
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
        return JobSearchForm(data=data, source_id=None)

    def get_context(self, request):
        return self.get_job_list_context(
            request, self.form.get_jobs(), self.form.get_job_counts()
        )

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
            Job.objects.exclude(job_name='check_source')
            .order_by('source', '-modify_date')
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
