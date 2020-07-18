"""
all general purpose function goes here
"""
import json
from functools import wraps
from datetime import datetime, timedelta

from dateutil.parser import parse
import pytz


def default_value(default_value_dict=None):
    """
    get default value for function.abs
    default_value_dict format is
    {
        key: function to calculate default value or value it self
    }
    """

    def _my_decorator(view_func):
        def _decorator(*args, **kwargs):
            if not isinstance(default_value_dict, dict):
                return view_func(*args, **kwargs)
            keys = default_value_dict.keys()
            for key in keys:
                value = kwargs.get(key, None)
                if value is not None:
                    continue
                default_fun = default_value_dict[key]
                if hasattr(default_fun, '__call__'):
                    value = default_fun()
                else:
                    value = default_fun
                kwargs[key] = value
            return view_func(*args, **kwargs)

        return wraps(view_func)(_decorator)

    return _my_decorator


def get_unix_start_time():
    """
    get start of unix timestamp
    """
    return datetime(1970, 1, 1).replace(tzinfo=pytz.UTC)


def get_now():
    """
    get current datetime in UTC
    """
    return datetime.utcnow().replace(tzinfo=pytz.UTC)


def get_today(now=get_now()):
    """
    get today's datetiem at midnight UTC
    """

    now = get_now()
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


@default_value({
    'day': get_now
})
def get_day(day=get_now()):
    """
    get given day's datetime at midnight
    """
    if not isinstance(day, datetime):
        raise ValueError('day should be of type datetime')

    return day.replace(hour=0, minute=0, second=0, microsecond=0)


@default_value({
    'now': get_now
})
def get_30_seconds_ago(now=get_now()):
    """
    get datetime last 30 seconds ago in UTC
    """
    if not isinstance(now, datetime):
        raise ValueError('now should be of type datetime')
    return now - timedelta(seconds=30)


@default_value({
    'now': get_now
})
def get_35_seconds_ago(now=get_now()):
    """
    get datetime last 35 seconds ago in UTC
    """
    if not isinstance(now, datetime):
        raise ValueError('now should be of type datetime')
    return now - timedelta(seconds=35)


@default_value({
    'now': get_now
})
def get_25_seconds_ago(now=get_now()):
    """
    get datetime last 35 seconds ago in UTC
    """
    if not isinstance(now, datetime):
        raise ValueError('now should be of type datetime')
    return now - timedelta(seconds=25)


@default_value({
    'now': get_now
})
def get_1_minute_ago(now=get_now()):
    """
    get datetime last 1 minute ago in UTC
    """
    if not isinstance(now, datetime):
        raise ValueError('now should be of type datetime')
    return now - timedelta(seconds=60)


def format_datetime(date, date_format):
    """
    formate date
    """
    if not isinstance(date, datetime):
        raise ValueError('date should be datetime')

    return date.strftime(date_format)


@default_value({
    'current_time': get_now
})
def get_current_epoch(current_time=None):
    """
    get current time in epoch
    """
    if not isinstance(current_time, datetime):
        raise ValueError('current_time should be datetime')

    epoch = (current_time - get_unix_start_time()).total_seconds() * 1000
    return int(epoch)


@default_value({
    'epoch': get_current_epoch
})
def get_datetime_epoch(epoch=get_current_epoch()):
    """
    convert epoch to datetime
    """
    epoch = int(int(epoch) / 1000)
    return datetime.fromtimestamp(epoch)


def convert_string_datetime(date_str):
    """
    convert date str into utc timezoned datetime
    """
    if not isinstance(date_str, (str, unicode)):
        raise ValueError('date_str should be string')
    return datetime.strptime(date_str, '%Y-%m-%d').replace(tzinfo=pytz.UTC)


@default_value({
    'now': get_now
})
def convert_to_utc(now=get_now()):
    """
    convert datetime to utc
    """
    if not isinstance(now, datetime):
        raise ValueError('now should be of datetime')

    return now.replace(tzinfo=pytz.UTC)


def convert_utc_string_datetime(date_str):
    """
    convert utc datetime utc to datetime
    """
    if not isinstance(date_str, (str, unicode)):
        raise ValueError('date_str should be string')
    return parse(str(date_str)).replace(tzinfo=pytz.UTC)


def convert_to_indian_timezone(date):
    """
    convert date to indian timezone
    """
    if not isinstance(date, datetime):
        raise ValueError('date should be datetime')

    if date.tzinfo is None:
        date = pytz.utc.localize(date)

    indina_timezone = pytz.timezone('Asia/Calcutta')
    localDatetime = date.astimezone(indina_timezone)
    return localDatetime


def convert_string_datetime_indian_timezone(date_str):
    """
    convert date str into utc timezoned datetime
    """
    if not isinstance(date_str, (str, unicode)):
        raise ValueError('date_str should be string')
    indina_timezone = pytz.timezone('Asia/Calcutta')
    return indina_timezone.localize(datetime.strptime(date_str, '%Y-%m-%d'))


def add_minutes(date, minutes=0):
    """
    add minute to current date
    """
    if not isinstance(date, datetime):
        raise ValueError('date should be datetime')
    return date + timedelta(minutes=minutes)
