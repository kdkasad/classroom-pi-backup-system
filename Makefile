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

.PHONY: all
all: provision.sh

# Extra dependency files for provision.sh
provision_sh_includes := \
	node/usr/local/lib/systemd/system/backup.service \
	node/usr/local/lib/systemd/system/backup.timer \
	node/etc/systemd/system/backup.service.d/00-triggers.conf \
	node/etc/systemd/system/backup.timer.d/00-times.conf
provision.sh: $(provision_sh_includes)

# Run *.sh.in through m4 to get *.sh
%.sh: %.sh.in
	@printf 'M4\t%s\n' '$@'
	$(M4) $(M4OPTS) $< > $@
