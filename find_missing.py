#!/usr/bin/env python3


#
#    Raspberry Pi Backup System for Classrooms - Find missing backups script
#    Copyright (C) 2022  Kian Kasad
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License, version 3, as
#    published by the Free Software Foundation.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.
#


import argparse
import asyncio
from asyncio.subprocess import PIPE
import datetime
import json
import os
import signal
import smtplib
import ssl
import sys

import dateutil.parser


# Configure variables below this line #

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

# Email sender (from) and recipients (to).
EMAIL_SENDER = None  # use env
EMAIL_RECIPIENTS = None  # use env

# Email server host and port.
# These must correspond to an SMTP over TLS server.
SMTP_SERVER = 'smtp.gmail.com'
SMTP_PORT = 465
SMTP_USE_SSL = True
SMTP_USERNAME = EMAIL_SENDER

# End configuration section #
# Don't change anything below this line #


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
Subject: Missing Raspberry Pi backups for {date}
"""


class BorgError(Exception):
    """Borg error type"""


def send_email(message):
    """Send an email with the given contents"""
    # Find sender email
    sender = os.getenv('EMAIL_SENDER') or EMAIL_SENDER
    if not sender:
        raise ValueError('Sender email unknown: Environment variable '
                         'EMAIL_SENDER is not set and no default exists.')

    # Find recipient emails
    recipients = os.getenv('EMAIL_RECIPIENTS')
    recipients = [x.strip() for x in recipients.split(',')] \
        if recipients else EMAIL_RECIPIENTS
    if not recipients:
        raise ValueError('Recipient emails unknown: Environment variable '
                         'EMAIL_RECIPIENTS is not set and no default exists.')

    # Find SMTP username
    username = os.getenv('SMTP_USERNAME') or SMTP_USERNAME or sender
    if not username:
        raise ValueError('SMTP username unknown: Environment variable '
                         'SMTP_USERNAME is not set and no default exists.')

    # Find SMTP password
    password = os.getenv('SMTP_PASSWORD')
    if not password:
        raise ValueError('SMTP password unknown: Environment variable '
                         'SMTP_PASSWORD is not set.')

    # Find SMTP server
    server = os.getenv('SMTP_SERVER') or SMTP_SERVER
    if not server:
        raise ValueError('SMTP server unknown: Environment variable '
                         'SMTP_SERVER is not set and no default exists.')

    # Find SMTP port
    try:
        port = int(os.getenv('SMTP_PORT') or SMTP_PORT)
    except (TypeError, ValueError) as err:
        raise ValueError(
            'SMTP port unknown: Environment variable SMTP_PORT is not set and '
            'no default exists or it is set and invalid.'
        ) from err
    try:
        port = int(port)
        assert 0 < port < 0x10000
    except (ValueError, TypeError) as err:
        raise ValueError('Invalid SMTP port number') from err

    # Find SMTP SSL setting
    use_ssl = bool(os.getenv('SMTP_USE_SSL') or SMTP_USE_SSL)

    # Send email
    sslctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(server, port, context=sslctx) if use_ssl \
            else smtplib.SMTP(server, port) \
            as smtp:
        smtp.login(username, password)
        smtp.sendmail(sender, recipients, message)


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

    def ignore_sigint():
        signal.signal(signal.SIGINT, signal.SIG_IGN)

    repo_path = os.path.join(REPO_PARENT_PATH, repo)
    cmd = [BORG_EXE, '--log-json', 'list', '--json', repo_path]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=PIPE, stderr=PIPE,
        close_fds=True, preexec_fn=ignore_sigint
    )
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
        raise BorgError(
            'Borg exited with error status:\n' +
            '\n'.join('(borg): ' + emsg for emsg in error_messages)
        )

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
    parser.add_argument(
        '--email', help='Send an email with the results', action='store_true'
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

    if args.email:
        email = EMAIL_HEADERS.rstrip().format(
            date=date,
            missing=' '.join(missing),
            failed=' '.join(e[0] for e in errors),
            errors='\n\n'.join(format_error(*e) for e in errors)
        ) + '\n\n' + message
        try:
            send_email(email)
        except Exception as err:
            print(ERROR_PREFIX, 'Failed to send email:', err, file=sys.stderr)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(3)
