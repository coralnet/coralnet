import csv
import datetime
import enum
import operator
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Count
from django.db.models.functions import TruncDay, TruncHour
from django.utils.timezone import (
    activate as activate_timezone, deactivate as deactivate_timezone)
import matplotlib.pyplot as plt

from ...models import Job


class Subject(enum.Enum):
    API_JOBS = 'api_jobs'
    JOB_QUEUE = 'job_queue'


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
        subject = options['subject']
        if not (span_end := options.get('span_end')):
            span_end = datetime.datetime.now(datetime.timezone.utc)
        self.span_days = options['span_days']
        span_length = datetime.timedelta(days=self.span_days)

        match subject:
            case Subject.API_JOBS.value:
                self.do_api_jobs(date_lt=span_end, date_gt=span_end-span_length)
            case Subject.JOB_QUEUE.value:
                TODO
            case _:
                raise ValueError(f"Unsupported subject: {subject}")

    def do_api_jobs(self, date_lt, date_gt):
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

        # trunc_function operates in the active timezone, so we temporary set
        # the active timezone to UTC to make everything else easier.
        activate_timezone(datetime.timezone.utc)
        api_jobs = (
            Job.objects
            .completed()
            .filter(
                job_name='classify_image',
                modify_date__lt=date_lt,
                modify_date__gt=date_gt,
            )
            .annotate(date_to_slice=trunc_function('modify_date'))
        )
        job_count_by_slice_values = (
            api_jobs
            .values('date_to_slice')
            .annotate(count=Count('id'))
        )
        job_count_by_slice = dict(
            (d['date_to_slice'], d['count'])
            for d in job_count_by_slice_values
        )
        deactivate_timezone()

        data = []
        current_slice = initial_slice
        while current_slice < date_lt:
            if current_slice in job_count_by_slice:
                jobs_completed = job_count_by_slice[current_slice]
            else:
                jobs_completed = 0
            data.append(dict(
                slice_display=current_slice.strftime(slice_dt_format),
                slice_tick_value=slice_tick_value_f(current_slice),
                slice_tick_display=slice_tick_display_f(current_slice),
                jobs_completed=jobs_completed,
            ))
            current_slice += slice_interval

        # Not sure if there's any guarantee on values() ordering, so
        # we ensure ordering ourselves.
        data.sort(key=operator.itemgetter('slice_tick_value'))

        span_total_jobs = sum(d['jobs_completed'] for d in data)

        # Save as CSV
        csv_path = Path(settings.COMMAND_OUTPUT_DIR) / 'recent_stats.csv'
        with open(csv_path, 'w', newline='', encoding='utf-8') as csv_f:
            fieldnames = [
                time_slice, 'jobs_completed',
            ]
            writer = csv.DictWriter(csv_f, fieldnames)
            writer.writeheader()

            for d in data:
                writer.writerow({
                    time_slice: d['slice_display'],
                    'jobs_completed': d['jobs_completed'],
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
        ax.set_title(
            f"Recent API jobs - {date_lt.strftime('%Y-%m-%d %H:%M UTC')}"
            f"\n{span_total_jobs} completed in last {self.span_days} day(s)")
        ax.set_xlabel(time_slice.title())
        ax.set_ylabel("Jobs")
        ax.set_xticks(
            [d['slice_tick_value'] for d in ticks],
            labels=[d['slice_tick_display'] for d in ticks],
        )
        ax.bar(
            [d['slice_tick_value'] for d in data],
            [d['jobs_completed'] for d in data],
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
