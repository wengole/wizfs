from __future__ import absolute_import
from datetime import datetime
import logging
from time import sleep
from decimal import Decimal
import os

from celery import task, group
from django.utils.timezone import get_default_timezone_name
import magic
import pytz

from .models import File, Filesystem


logger = logging.getLogger(__name__)


@task()
def create_file_object(full_path, snapshot=None, directory=False):
    logger.info('Adding %s: %s',
                ('directory' if directory else 'file'), full_path)
    statinfo = os.stat(full_path)
    mtime = datetime.fromtimestamp(statinfo.st_mtime)
    mtime = pytz.timezone(get_default_timezone_name()).localize(mtime)
    try:
        magic_info = magic.from_file(full_path)
    except magic.MagicException:
        magic_info = ''
    try:
        mime_type = magic.from_file(full_path, mime=True)
    except magic.MagicException:
        mime_type = ''
    File.objects.get_or_create(
        full_path=full_path,
        snapshot=snapshot,
        directory=directory,
        mime_type=mime_type,
        magic=magic_info,
        modified=mtime,
        size=statinfo.st_size,
    )
    sleep(.1)


@task(bind=True)
def reindex_filesystem(self, fs_name):
    """
    Task to walk a given filesystem (which may be a snapshot) and index all
    files and directories within it
    """
    self.total_files = 0
    self.groups = []
    self.update_count = 0
    self.update_rate = 10

    def jobs(self):
        """
        The individual jobs in all groups currently queued
        """
        return [job for group in self.groups for job in group.children]

    def done_files(self):
        """
        The number of files that have been indexed so far
        """
        done = sum([int(x.ready()) for x in jobs(self)])
        return done

    def work_to_do(self):
        """
        Are there any outstanding jobs to complete?
        """
        to_do = any([not job.ready() for job in self.groups])
        return to_do

    def update_progress(self):
        """
        Set the task state to PROGRESS and add metadata about the progress of
        the task
        """
        if self.update_count < self.update_rate:
            self.update_count += 1
            return
        self.update_count = 0
        done = Decimal(done_files(self))
        total = Decimal(self.total_files)
        self.update_state(
            state='PROGRESS',
            meta={
                'percentage': done / total * 100,
                'done': done_files(self),
                'total': self.total_files
            }
        )

    try:
        fs = Filesystem.objects.get(
            name=fs_name
        )
    except Filesystem.DoesNotExist:
        logger.error('Filesystem "%s" does not exist', fs_name)
        # TODO: Raise an error so Celery knows the task failed and why
        return
    for dirname, subdirs, files in fs.walk_fs():
        logger.info('Adding subdirs for %s', dirname)
        self.total_files += len(subdirs)
        subdirs_job = group([create_file_object.s(
            full_path=u'%s/%s' % (dirname, s),
            directory=True
        ) for s in subdirs])
        self.groups.append(subdirs_job.apply_async())
        update_progress(self)

        logger.info('Adding files for %s', dirname)
        self.total_files += len(files)
        files_job = group([create_file_object.s(
            full_path=u'%s/%s' % (dirname, f)
        ) for f in files])
        self.groups.append(files_job.apply_async())
        update_progress(self)

    update_progress(self)
    logger.info('All files and directories queued')
    if work_to_do(self):
        logger.debug('Still waiting on %d jobs',
                    self.total_files - done_files(self))

    while work_to_do(self):
        update_progress(self)
        logger.debug('Still waiting on %d jobs',
                    self.total_files - done_files(self))
