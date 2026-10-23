"""Typed NTULearn responses grouped by domain."""

from .common import LearnError, Model, AuthStatus, Freshness, Issue, ScanResult
from .courses import Course, Courses, Content, Contents, ContentNode, ContentTree, ContentMatch, ContentSearch
from .files import Attachment, Attachments, Download, FileContent, CourseDownloadFile, CourseDownload
from .people import Person, CourseUsers, Group, CourseGroups
from .grades import GradeColumn, Grade, Gradebook
from .messages import MessageSummary, Messages, MessageDetail
from .activity import Announcement, Announcements, CalendarItem, Calendar, Upcoming, RecentAnnouncement, RecentGrade, Digest

__all__ = [
    'LearnError',
    'Model',
    'AuthStatus',
    'Freshness',
    'Issue',
    'ScanResult',
    'Course',
    'Courses',
    'Content',
    'Contents',
    'ContentNode',
    'ContentTree',
    'ContentMatch',
    'ContentSearch',
    'Attachment',
    'Attachments',
    'Download',
    'FileContent',
    'CourseDownloadFile',
    'CourseDownload',
    'Person',
    'CourseUsers',
    'Group',
    'CourseGroups',
    'GradeColumn',
    'Grade',
    'Gradebook',
    'MessageSummary',
    'Messages',
    'MessageDetail',
    'Announcement',
    'Announcements',
    'CalendarItem',
    'Calendar',
    'Upcoming',
    'RecentAnnouncement',
    'RecentGrade',
    'Digest',
]
