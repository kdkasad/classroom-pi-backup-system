#!/bin/sh


#
#    Raspberry Pi Backup System for Classrooms - Node Provisioning Script
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


# Change the following two lines to match your backup server
SERVER_IP='10.205.8.217'
SERVER_PORT=36888

### Do not change anything below this line ###

HOSTNAME_PATTERN='[A-Z0-9][A-Z0-9\-]*'

# Set new hostname given by user
change_hostname() {
	local response

	# Prompt user for new hostname
	printf 'Enter a new hostname: ' >&2
	# Read from /dev/tty as stdin might be a pipe
	IFS='' read -r response < /dev/tty
	until
		printf '%s' "$response" | grep -ixq "$HOSTNAME_PATTERN"
	do
		printf '\033[1;31mError:\033[m %s %s\n' 'Invalid hostname.' \
			'The hostname may only contain letters, numbers, and hyphens.'
		printf 'Ente a new hostname: ' >&2
		IFS='' read -r response < /dev/tty
	done

	# Set new hostname. Attempts to use hostnamectl(1) first. If that fails,
	# writes the new name to /etc/hostname then updates the live hostname using
	# hostname(1) or /proc/sys/kernel/hostname.
	printf "\033[1;34mInfo:\033[m Setting new hostname to '%s'.\n" "$response" >&2
	sed -i "/^127\.0\.[01]\.1\s\+$(hostname)\s*$/d" /etc/hosts
	printf '127.0.1.1\t%s\n' "$response" >> /etc/hosts
	if ! \
		hostnamectl --no-ask-password --static --pretty hostname "$response" \
			2>/dev/null
	then
		printf '%s\n' "$response" > /etc/hostname
		if ! \
			hostname "$response" 2>/dev/null
		then
			printf '%s' "$response" > /proc/sys/kernel/hostname
		fi
	fi
}

set -e

# Ensure we're running as root
if [ $(id -u) -ne 0 ]
then
	printf '\033[1;31m%s\033[m %s\n' 'Error:' \
		'This script must be run as root.' >&2
	if [ -x "$0" ]
	then
		printf "\033[1;32mHint:\033[m Try running 'sudo %s'.\n" "$0"
	fi
	exit 1
fi

# If the hostname has not been changed, prompt for a new one.
# If it appears to have been changed, print the detected hostname.
hostname="$(hostname)"
if [ "$hostname" = "raspberrypi" ]
then
	printf "\033[1;33mWarning:\033[m You're using the default hostname '%s'.\n" "$hostname" >&2
	change_hostname
elif ! printf '%s' "$hostname" | grep -ixq "$HOSTNAME_PATTERN"
then
	printf "\033[1;33mWarning:\033[m Invalid or no hostname detected.\n" >&2
	change_hostname
fi

# Install required packages
apt-get update -qq
apt-get install --no-install-recommends -qq \
	borgbackup openssh-client python3 python3-requests curl bash

# Create systemd parent directories
install -d -m 755 \
	/usr/local/lib/systemd/system \
	/etc/systemd/system/backup.service.d \
	/etc/systemd/system/backup.timer.d

# Create backup service unit
umask 022
cat <<- 'EOF' > /usr/local/lib/systemd/system/backup.service
[Unit]
Description=Back up user files
Requires=network-online.target network.target
After=network-online.target network.target
Before=shutdown.target

[Service]
StateDirectory=backup_client
Type=oneshot
ExecStart=/usr/local/lib/backup_client.py
EOF

cat <<- 'EOF' > /etc/systemd/system/backup.service.d/00-triggers.conf
[Install]
WantedBy=shutdown.target
EOF

# Create backup timer unit
cat <<- 'EOF' > /usr/local/lib/systemd/system/backup.timer
[Unit]
Description=Timer for backup service

[Timer]
Unit=backup.service
WakeSystem=on
OnCalendar=00:00
AccuracySec=15sec

[Install]
WantedBy=timers.target
EOF

echo '[Timer]' > /etc/systemd/system/backup.timer.d/00-times.conf

# Download SSH key
umask 022
install -d -m 755 /usr/local/share/backup_client
curl -fsSL "http://$SERVER_IP:$SERVER_PORT/setup/node_key" \
	> /usr/local/share/backup_client/ssh_key

# Download client script
install -d -m 755 /usr/local/lib
umask 027
curl -fsSL "http://$SERVER_IP:$SERVER_PORT/setup/client.py" \
	> /usr/local/lib/backup_client.py
chmod 750 /usr/local/lib/backup_client.py
umask 022

# Reload systemd and enable units
systemctl daemon-reload
systemctl enable --now backup.service
systemctl enable --now backup.timer

exit 0
