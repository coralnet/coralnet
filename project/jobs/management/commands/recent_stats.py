import csv
import datetime
import enum
import operator
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Count, F
from django.db.models.functions import TruncDay, TruncHour
from django.utils.timezone import (
    activate as activate_timezone, deactivate as deactivate_timezone)
import matplotlib.pyplot as plt

from ...models import Job
from ...utils import get_job_names_by_task_queue, Time90Percentile


class Subject(enum.Enum):
    API_JOBS = 'api_jobs'
    TURNAROUND_TIME = 'turnaround_time'


class Command(BaseCommand):
    help = (
        "Collect and display stats about recent job activity."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            'subject', type=str,
            help=f"Subject to collect stats for. Accepted values:"
                 f" {', '.join([e.value for e in Subject])}"
        )
        parser.add_argument(
            '--span_days', type=int, default=30,
            help=f"Timespan to collect stats for, in days."
        )
        parser.add_argument(
            '--span_end', type=str,
            help=f"End date for the timespan. If not given, then now() is used."
        )

    def handle(self, *args, **options):
        if not (span_end := options.get('span_end')):
            span_end = datetime.datetime.now(datetime.timezone.utc)
        self.span_days = options['span_days']
        span_length = datetime.timedelta(days=self.span_days)

        date_lt = span_end
        date_gt = span_end-span_length

        # Have time granularity depend on the length of the full time span.
        if self.span_days >= 6:
            time_slice = 'day'
            trunc_function = TruncDay
            initial_slice = date_gt.replace(
                hour=0, minute=0, second=0, microsecond=0)
            slice_interval = datetime.timedelta(days=1)
            slice_dt_format = '%Y-%m-%d xx:xx'
            def slice_tick_value_f(slice_):
                # Value that goes up 1 for each day, across months etc.
                return slice_.toordinal()
            def slice_tick_display_f(slice_):
                # Number from 01-31.
                return format(slice_.day, '02d')
        else:
            time_slice = 'hour'
            trunc_function = TruncHour
            initial_slice = date_gt.replace(
                minute=0, second=0, microsecond=0)
            slice_interval = datetime.timedelta(hours=1)
            slice_dt_format = '%Y-%m-%d %H:xx'
            def slice_tick_value_f(slice_):
                # Value that goes up 1 for each hour, across days etc.
                return slice_.toordinal()*24 + getattr(slice_, 'hour')
            def slice_tick_display_f(slice_):
                # Number from 00-23.
                return format(slice_.hour, '02d')

        subject = options['subject']
        match subject:
            case Subject.API_JOBS.value:
                value_by_slice = self.api_jobs_completed_by_slice(
                    date_lt, date_gt, trunc_function)
                slice_value_label = 'jobs_completed'
                slice_value_label_for_axis = "Jobs completed"
                span_total_completed = sum(
                    count for count in value_by_slice.values())
                plot_title = (
                    f"Recent API jobs"
                    f" - {date_lt.strftime('%Y-%m-%d %H:%M UTC')}"
                    f"\n{span_total_completed} completed"
                    f" in last {self.span_days} day(s)"
                )
                def plot_f(axes_, x_, y_):
                    axes_.bar(x_, y_)
            case Subject.TURNAROUND_TIME.value:
                value_by_slice = self.turnaround_time_by_slice(
                    date_lt, date_gt, trunc_function)
                slice_value_label = 'turnaround_time'
                slice_value_label_for_axis = "Minutes elapsed"
                plot_title = (
                    f"Recent job turnaround times"
                    f" - {date_lt.strftime('%Y-%m-%d %H:%M UTC')}"
                    f"\n90th-percentile times in last {self.span_days} day(s)"
                )
                def plot_f(axes_, x_, y_):
                    axes_.plot(x_, y_)
            case _:
                raise ValueError(f"Unsupported subject: {subject}")

        data = []
        current_slice = initial_slice
        while current_slice < date_lt:
            if current_slice in value_by_slice:
                slice_value = value_by_slice[current_slice]
            else:
                slice_value = 0
            data.append(dict(
                slice_display=current_slice.strftime(slice_dt_format),
                slice_tick_value=slice_tick_value_f(current_slice),
                slice_tick_display=slice_tick_display_f(current_slice),
                slice_value=slice_value,
            ))
            current_slice += slice_interval

        # Not sure if there's any guarantee on values() ordering, so
        # we ensure ordering ourselves.
        data.sort(key=operator.itemgetter('slice_tick_value'))

        # Save as CSV
        csv_path = Path(settings.COMMAND_OUTPUT_DIR) / 'recent_stats.csv'
        with open(csv_path, 'w', newline='', encoding='utf-8') as csv_f:
            fieldnames = [
                time_slice, slice_value_label,
            ]
            writer = csv.DictWriter(csv_f, fieldnames)
            writer.writeheader()

            for d in data:
                writer.writerow({
                    time_slice: d['slice_display'],
                    slice_value_label: d['slice_value'],
                })
        self.stdout.write(f"Output: {csv_path}")

        # Ensure the x-ticks aren't too crowded.
        tick_count = len(data)
        visible_tick_step = 1
        max_ticks = 60
        while tick_count > max_ticks:
            tick_count /= 2
            visible_tick_step *= 2
        ticks = data[::visible_tick_step]

        fig = plt.gcf()
        ax = fig.add_subplot(111)
        ax.set_title(plot_title)
        ax.set_xlabel(time_slice.title())
        ax.set_ylabel(slice_value_label_for_axis)
        ax.set_xticks(
            [d['slice_tick_value'] for d in ticks],
            labels=[d['slice_tick_display'] for d in ticks],
        )
        plot_f(
            ax,
            [d['slice_tick_value'] for d in data],
            [d['slice_value'] for d in data],
        )

        # Save as plot image.
        # Have dimensions depend on the number of points; more points = wider.
        max_aspect_ratio = 4.0
        aspect_ratio = len(data) * (max_ticks / max_aspect_ratio)
        # But also cap the min/max of the aspect ratio.
        aspect_ratio = min(max(1.0, aspect_ratio), max_aspect_ratio)
        fig.set_size_inches(aspect_ratio*5, 5)
        plot_path = Path(settings.COMMAND_OUTPUT_DIR) / 'recent_stats.png'
        plt.savefig(plot_path)
        self.stdout.write(f"Output: {plot_path}")

    @staticmethod
    def api_jobs_completed_by_slice(date_lt, date_gt, trunc_function):
        # trunc_function operates in the active timezone, so we temporarily
        # set the active timezone to UTC to make everything else easier.
        activate_timezone(datetime.timezone.utc)
        completed_api_jobs = (
            Job.objects
            .completed()
            .filter(
                job_name='classify_image',
                modify_date__lt=date_lt,
                modify_date__gt=date_gt,
            )
            .annotate(date_to_slice=trunc_function('modify_date'))
        )
        count_by_slice_values = (
            completed_api_jobs
            .values('date_to_slice')
            .annotate(count=Count('id'))
        )
        count_by_slice = dict(
            (d['date_to_slice'], d['count'])
            for d in count_by_slice_values
        )
        deactivate_timezone()

        return count_by_slice

    @staticmethod
    def turnaround_time_by_slice(date_lt, date_gt, trunc_function):
        activate_timezone(datetime.timezone.utc)
        background_jobs = Job.objects.filter(
            job_name__in=get_job_names_by_task_queue()['background'])
        completed_bg_jobs = (
            background_jobs
            .completed()
            .filter(
                modify_date__lt=date_lt,
                modify_date__gt=date_gt,
            )
            .annotate(date_to_slice=trunc_function('modify_date'))
            .annotate(
                turnaround_time=F('modify_date')-F('scheduled_start_date'))
        )
        time_by_slice_values = (
            completed_bg_jobs
            .values('date_to_slice')
            .annotate(time=Time90Percentile('turnaround_time'))
        )
        time_by_slice = dict(
            (d['date_to_slice'], d['time'].seconds / 60)
            for d in time_by_slice_values
        )
        deactivate_timezone()

        return time_by_slice
