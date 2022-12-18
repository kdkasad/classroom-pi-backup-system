#!/usr/bin/env python3

import argparse
import asyncio
from asyncio.subprocess import PIPE
import datetime
import json
import os
import sys

import dateutil.parser


### Configure variables below this line ###

# Borg executable path
BORG_EXE = '/usr/bin/borg'

# Number of Borg processes to run concurrently.
# Higher numbers mean higher CPU and memory usage, but faster processing.
CONCURRENT_BORG_PROCS = 12

# Specify repositories.
# Will be constructed as REPO_PARENT_PATH/repo for each repo in REPOS_TO_CHECK.
REPO_PARENT_PATH = os.path.expanduser('~/repos')
REPOS_TO_CHECK = sorted([
    'A0', 'A9',
    *(x + i for x in 'ABCD' for i in '12345678'),
])

### End configuration section ###
### Don't change anything below this line ###


ERROR_PREFIX = '\x1b[1;31mError\x1b[m:'
WARNING_PREFIX = '\x1b[1;33mWarning\x1b[m:'

MISSING_MESSAGE_FORMAT = """\
The following Raspberry Pi's did not back up on {date}:
{missing}
"""
SUCCESS_MESSAGE_FORMAT = """\
No missing backups for {date}.
"""
FAILED_MESSAGE_FORMAT = """\
Errors were encountered while attempting to process the following
backup repositories:
{failed}


{errors}
"""

EMAIL_HEADERS = """\
From: {sender}
To: {recipients}
Subject: Missing Raspberry Pi backups for {date}
"""


class BorgError(Exception):
    """Borg error type"""


async def check_repo_is_missing_backups(repo, date):
    """
    Checks if a repository is missing backups for a given date.

    Parameters:
        repo (str): The path to the repository to check
        date (datetime.date): The date to use for checking

    Returns:
        True if the repository is missing backups for the
        given date and False otherwise.
    """
    repo_path = os.path.join(REPO_PARENT_PATH, repo)
    cmd = [BORG_EXE, '--log-json', 'list', '--json', repo_path]
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
    stdout, stderr = await proc.communicate()

    if proc.returncode == 2:
        # Error occurred within Borg
        error_messages = []
        for line in stderr.splitlines():
            try:
                msg = json.loads(line)
                if msg.get('msgid') == 'Repository.DoesNotExist':
                    return True
                elif 'message' in msg:
                    error_messages.append(msg['message'])
            except json.JSONDecodeError:
                pass  # ignore non-JSON lines
        raise BorgError('Borg exited with error status:\n' +
                        '\n'.join('(borg): ' + emsg for emsg in error_messages))

    repo = json.loads(stdout)
    archives = repo['archives']
    for archive in archives:
        timestamp = datetime.datetime.fromisoformat(archive['time'])
        if timestamp.date() == date:
            return False
    return True


def format_error(repo, err):
    return """\
Error details for repository '{repo}':
{name}: {err}
""".format(name=type(err).__name__, err=err, repo=repo)


async def do_with_sem(sem, func, *args):
    """Run async function `func' after acquiring Semaphore `sem'."""
    async with sem:
        return await func(*args)


async def main():
    """Main function"""

    # Parse command-line args
    parser = argparse.ArgumentParser()
    parser.add_argument(
        'date', help='Date for which to check for missing backups', nargs='?'
    )
    args = parser.parse_args()

    # Create datetime.date object from date string
    if args.date:
        try:
            date = dateutil.parser.parse(args.date).date()
        except dateutil.parser.ParserError:
            print(ERROR_PREFIX, f"Invalid date format '{args.date}'",
                  file=sys.stderr)
            sys.exit(1)
    else:
        today = datetime.date.today()
        yesterday = today.replace(day=today.day - 1)
        print(WARNING_PREFIX, "Using yesterday's date,",
              yesterday, file=sys.stderr)
        date = yesterday

    # Perform checks
    sem = asyncio.Semaphore(CONCURRENT_BORG_PROCS)
    results = await asyncio.gather(
        *(do_with_sem(sem, check_repo_is_missing_backups, repo, date)
          for repo in REPOS_TO_CHECK),
        return_exceptions=True
    )

    # Sort results
    missing = []
    errors = []
    for repo, result in zip(REPOS_TO_CHECK, results):
        if result is True:
            missing.append(repo)
        elif result is False:
            pass  # do nothing
        else:
            errors.append((repo, result))

    message = ''
    if missing:
        # Format and print response message
        message += MISSING_MESSAGE_FORMAT.rstrip().format(
            date=date,
            missing=' '.join(missing),
            failed=' '.join(e[0] for e in errors),
            errors='\n\n'.join(format_error(*e) for e in errors)
        )
    else:
        message += SUCCESS_MESSAGE_FORMAT.rstrip().format(
            date=date,
            missing=' '.join(missing),
            failed=' '.join(e[0] for e in errors),
            errors='\n\n'.join(format_error(*e) for e in errors)
        )
    if errors:
        message += '\n\n'
        message += FAILED_MESSAGE_FORMAT.rstrip().format(
            date=date,
            missing=' '.join(missing),
            failed=' '.join(e[0] for e in errors),
            errors='\n\n'.join(format_error(*e) for e in errors)
        )
    print(message)


if __name__ == '__main__':
    asyncio.run(main())
