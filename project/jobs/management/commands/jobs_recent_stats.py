from collections import Counter, defaultdict
import csv
import datetime
import enum
import operator
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Avg, Count, F
from django.db.models.functions import TruncDay, TruncHour
from django.utils.timezone import (
    activate as activate_timezone, deactivate as deactivate_timezone)
import matplotlib.pyplot as plt
import numpy as np

from api_core.models import ApiJobUnit
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
            help=f"End date for the timespan, in ISO format."
                 f" If timezone not given, UTC is assumed."
                 f" If this arg is absent, now() is used."
        )

    def handle(self, *args, **options):
        span_end_str = options.get('span_end')
        if span_end_str:
            self.span_end = datetime.datetime.fromisoformat(span_end_str)
            if not self.span_end.tzinfo:
                self.span_end = self.span_end.replace(
                    tzinfo=datetime.timezone.utc)
        else:
            self.span_end = datetime.datetime.now(datetime.timezone.utc)

        self.span_days = options['span_days']
        span_length = datetime.timedelta(days=self.span_days)
        self.span_start = self.span_end - span_length

        # Have time granularity depend on the length of the full time span.
        if self.span_days >= 6:
            self.time_slice_name = 'day'
            self.date_trunc_function = TruncDay
            self.initial_slice = self.span_start.replace(
                hour=0, minute=0, second=0, microsecond=0)
            self.slice_interval = datetime.timedelta(days=1)
            self.slice_dt_format = '%Y-%m-%d xx:xx'
            # Value that goes up 1 for each day, across months etc.
            self.slice_tick_value_f = lambda slice_: slice_.toordinal()
            # Number from 01-31.
            self.slice_tick_display_f = (
                lambda slice_: format(slice_.day, '02d'))
        else:
            self.time_slice_name = 'hour'
            self.date_trunc_function = TruncHour
            self.initial_slice = self.span_start.replace(
                minute=0, second=0, microsecond=0)
            self.slice_interval = datetime.timedelta(hours=1)
            self.slice_dt_format = '%Y-%m-%d %H:xx'
            # Value that goes up 1 for each hour, across days etc.
            self.slice_tick_value_f = (
                lambda slice_: slice_.toordinal()*24 + getattr(slice_, 'hour'))
            # Number from 00-23.
            self.slice_tick_display_f = (
                lambda slice_: format(slice_.hour, '02d'))

        subject = options['subject']
        match subject:
            case Subject.API_JOBS.value:
                self.do_api_jobs()
            case Subject.TURNAROUND_TIME.value:
                self.do_turnaround_time()
            case _:
                raise ValueError(f"Unsupported subject: {subject}")

    def slice_display(self, slice_: datetime.datetime):
        return slice_.strftime(self.slice_dt_format)

    def make_data_series(self, value_by_slice):
        data_series = []
        current_slice = self.initial_slice
        while current_slice < self.span_end:
            if current_slice in value_by_slice:
                slice_value = value_by_slice[current_slice]
            else:
                slice_value = 0
            data_series.append(dict(
                slice_display=self.slice_display(current_slice),
                slice_tick_value=self.slice_tick_value_f(current_slice),
                slice_tick_display=self.slice_tick_display_f(current_slice),
                slice_value=slice_value,
            ))
            current_slice += self.slice_interval

        # Assume no guarantee on ordering of the input.
        # (Input may have come from QuerySet.values(), and we're not sure
        # if that guarantees an ordering.)
        data_series.sort(key=operator.itemgetter('slice_tick_value'))

        return data_series

    def save_csv(self, csv_data: list[dict], fieldnames=None):
        csv_path = Path(settings.COMMAND_OUTPUT_DIR) / 'jobs_recent_stats.csv'

        with open(csv_path, 'w', newline='', encoding='utf-8') as csv_f:
            if not fieldnames:
                fieldnames = csv_data[0].keys()
            writer = csv.DictWriter(csv_f, fieldnames)
            writer.writeheader()

            for d in csv_data:
                writer.writerow(d)

        self.stdout.write(f"Output: {csv_path}")

    def plot_prep(self, any_data_series, title, ylabel):
        # Ensure the x-ticks aren't too crowded.
        tick_count = len(any_data_series)
        visible_tick_step = 1
        max_ticks = 60
        while tick_count > max_ticks:
            tick_count /= 2
            visible_tick_step *= 2
        ticks = any_data_series[::visible_tick_step]

        fig = plt.gcf()
        ax = fig.add_subplot(111)
        ax.set_title(title)
        ax.set_xlabel(self.time_slice_name.title())
        ax.set_ylabel(ylabel)
        ax.set_xticks(
            [d['slice_tick_value'] for d in ticks],
            labels=[d['slice_tick_display'] for d in ticks],
        )
        return fig, ax

    def save_plot(self, fig):
        aspect_ratio = 3.0
        fig.set_size_inches(aspect_ratio*5, 5)
        plot_path = Path(settings.COMMAND_OUTPUT_DIR) / 'jobs_recent_stats.png'
        plt.savefig(plot_path)
        self.stdout.write(f"Output: {plot_path}")

    def do_api_jobs(self):
        # self.date_trunc_function operates in the active timezone,
        # so we temporarily set the active timezone to UTC
        # to make everything else easier.
        activate_timezone(datetime.timezone.utc)
        completed_api_job_units = (
            ApiJobUnit.objects
            .filter(
                internal_job__status__in=[
                    Job.Status.SUCCESS, Job.Status.FAILURE],
                internal_job__modify_date__gt=self.span_start,
                internal_job__modify_date__lt=self.span_end,
            )
            .annotate(
                date_to_slice=self.date_trunc_function(
                    'internal_job__modify_date')
            )
        )
        count_by_slice_and_user_values = (
            completed_api_job_units
            .values('date_to_slice', 'parent__user__username')
            .annotate(count=Count('id'))
            .order_by('date_to_slice', 'parent__user__username')
        )
        count_by_slice_and_user = dict()
        for d in count_by_slice_and_user_values:
            count_by_slice_and_user[
                (d['date_to_slice'], d['parent__user__username'])] = d['count']

        average_points_by_user_values = (
            completed_api_job_units
            .values('parent__user__username')
            .annotate(average_points=Avg('size'))
            .order_by('parent__user__username')
        )
        average_points_by_user = dict(
            (d['parent__user__username'], d['average_points'])
            for d in average_points_by_user_values
        )
        deactivate_timezone()

        # Fill in 0s for missing slice+user combos to prevent potential
        # issues later.
        all_slices = list(set(
            slice_ for (slice_, user) in count_by_slice_and_user.keys()
        ))
        all_users = list(set(
            user for (slice_, user) in count_by_slice_and_user.keys()
        ))
        for slice_ in all_slices:
            for user in all_users:
                if (slice_, user) not in count_by_slice_and_user:
                    count_by_slice_and_user[(slice_, user)] = 0

        span_total_completed_by_user = Counter()
        for (slice_, user), count in count_by_slice_and_user.items():
            span_total_completed_by_user.update(**{user: count})
        span_total_completed = span_total_completed_by_user.total()

        users_in_legend = [
            user
            for user, count
            # Up to 5 users in legend.
            in span_total_completed_by_user.most_common(5)
            # And each must have at least 1% share of all jobs.
            if count >= span_total_completed / 100
        ]

        # Use lambda to get a defaultdict of defaultdict.
        # https://stackoverflow.com/questions/5029934/defaultdict-of-defaultdict
        categories_count_by_slice = defaultdict(lambda: defaultdict(int))

        for (slice_, user), count in count_by_slice_and_user.items():
            if user in users_in_legend:
                categories_count_by_slice[user][slice_] = count
            else:
                # Users that don't qualify for the legend are grouped
                # into "Others".
                categories_count_by_slice["Others"][slice_] += count

        plot_data = dict()
        for category, count_by_slice in categories_count_by_slice.items():
            plot_data[category] = self.make_data_series(count_by_slice)

        slices_count_by_user = defaultdict(dict)
        for (slice_, user), count in count_by_slice_and_user.items():
            slices_count_by_user[slice_][user] = count

        csv_data = [
            {self.time_slice_name: self.slice_display(slice_)}
            |
            count_by_user
            for slice_, count_by_user in slices_count_by_user.items()
        ]
        # These aren't time slices, but they're useful to include in the CSV.
        csv_data.append(
            {self.time_slice_name: "Total"}
            |
            span_total_completed_by_user
        )
        csv_data.append(
            {self.time_slice_name: "Avg points per image"}
            |
            {user: format(avg, '.3f')
             for user, avg in average_points_by_user.items()}
        )
        self.save_csv(
            csv_data=csv_data,
            fieldnames=[self.time_slice_name] + sorted(list(all_users)),
        )

        plot_title = (
            f"Recent API jobs"
            f" - {self.span_end.strftime('%Y-%m-%d %H:%M UTC')}"
            f"\n{span_total_completed} completed"
            f" in last {self.span_days} day(s)"
        )
        any_data_series = plot_data[users_in_legend[0]]
        fig, ax = self.plot_prep(
            any_data_series, plot_title, "Jobs completed")
        # Incrementing bottom for each category will stack the different
        # categories' bars instead of overlapping them.
        bottom = np.zeros(len(any_data_series))

        for category, data_series in plot_data.items():
            category_total = Counter(
                categories_count_by_slice[category]).total()
            if category == "Others":
                label = f"{category} ({category_total} jobs)"
            else:
                ppi = average_points_by_user[category]
                label = (
                    f"{category} ({category_total} jobs, {ppi:.1f} pts/img)"
                )

            x = np.array([d['slice_tick_value'] for d in data_series])
            y = np.array([d['slice_value'] for d in data_series])
            ax.bar(
                x,
                y,
                label=label,
                bottom=bottom,
            )
            ax.legend()
            bottom += y

        self.save_plot(fig)

    def do_turnaround_time(self):
        activate_timezone(datetime.timezone.utc)
        background_jobs = Job.objects.filter(
            job_name__in=get_job_names_by_task_queue()['background'])
        completed_bg_jobs = (
            background_jobs
            .completed()
            .filter(
                modify_date__gt=self.span_start,
                modify_date__lt=self.span_end,
            )
            .annotate(date_to_slice=self.date_trunc_function('modify_date'))
            .annotate(
                turnaround_time=F('modify_date')-F('scheduled_start_date'))
        )
        time_by_slice_values = (
            completed_bg_jobs
            .values('date_to_slice')
            .annotate(time=Time90Percentile('turnaround_time'))
        )
        time_by_slice = dict(
            (d['date_to_slice'],
             d['time'].seconds / 60 if d['time'] else 0)
            for d in time_by_slice_values
        )
        deactivate_timezone()

        plot_data = self.make_data_series(time_by_slice)

        self.save_csv([
            {
                self.time_slice_name: d['slice_display'],
                'turnaround_time': d['slice_value'],
            }
            for d in plot_data
        ])

        plot_title = (
            f"Recent job turnaround times"
            f" - {self.span_end.strftime('%Y-%m-%d %H:%M UTC')}"
            f"\n90th-percentile times in last {self.span_days} day(s)"
        )
        fig, ax = self.plot_prep(plot_data, plot_title, "Minutes elapsed")

        ax.plot(
            [d['slice_tick_value'] for d in plot_data],
            [d['slice_value'] for d in plot_data],
        )

        self.save_plot(fig)
