#!/usr/bin/make -f

#
#    Raspberry Pi Backup System for Classrooms - Makefile
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


M4 := m4
M4OPTS := -P

RM := rm

##---- Don't change settings below this line ----##

include config.mk

M4OPTS += \
	-D m4_SERVER_IP=$(SERVER_IP)    \
	-D m4_HTTPD_PORT=$(HTTPD_PORT)  \
	-D m4_SSHD_PORT=$(SSHD_PORT)

TARGETS := \
	provision.sh \
	client.py \
	server/var/lib/backup/config/config_server_settings.env

.PHONY: all
all: $(TARGETS)

# Don't echo recipe commands unless $(ECHO) is set
$(ECHO).SILENT:

.PHONY: clean
clean: $(TARGETS)
	for file in $^; do printf 'RM\t%s\n' "$$file"; done
	$(RM) -f $^

# Rule to run *.sh.in through M4 to get *.sh
%.sh: %.sh.in config.mk
	@printf 'M4\t%s\n' '$@'
	$(M4) $(M4OPTS) $< > $@

# Rule to run *.py.in through M4 to get *.py
%.py: %.py.in config.mk
	@printf 'M4\t%s\n' '$@'
	$(M4) $(M4OPTS) $< > $@

# Rule to run *.env.in through M4 to get *.env
%.env: %.env.in config.mk
	@printf 'M4\t%s\n' '$@'
	$(M4) $(M4OPTS) $< > $@

# Extra dependency files for provision.sh
provision_sh_includes := \
	node/usr/local/lib/systemd/system/backup.service              \
	node/usr/local/lib/systemd/system/backup-on-shutdown.service  \
	node/usr/local/lib/systemd/system/backup.timer                \
	node/etc/systemd/system/backup.timer.d/00-times.conf
provision.sh: $(provision_sh_includes)
