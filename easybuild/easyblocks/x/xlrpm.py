##
# Copyright 2009-2013 Ghent University
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://vscentrum.be/nl/en),
# the Hercules foundation (http://www.herculesstichting.be/in_English)
# and the Department of Economy, Science and Innovation (EWI) (http://www.ewi-vlaanderen.be/en).
#
# http://github.com/hpcugent/easybuild
#
# EasyBuild is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation v2.
#
# EasyBuild is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with EasyBuild.  If not, see <http://www.gnu.org/licenses/>.
##
"""
EasyBuild support for installing RPMs without rebuilding, implemented as an easyblock.

@author: Stijn De Weirdt (Ghent University)
@author: Dries Verdegem (Ghent University)
@author: Kenneth Hoste (Ghent University)
@author: Pieter De Baets (Ghent University)
@author: Jens Timmerman (Ghent University)
@author: Toon Willems (Ghent University)
@author: Jack Perdue (Texas A&M University)
"""

import glob
import os
import re
import tempfile
from distutils.version import LooseVersion
from os.path import expanduser
from vsc.utils import fancylogger

import easybuild.tools.environment as env
from easybuild.easyblocks.generic.binary import Binary
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.run import run_cmd
from easybuild.tools.systemtools import check_os_dependency
from easybuild.easyblocks.generic.rpm import Rpm


_log = fancylogger.getLogger('easyblocks.generic.rpm')


class XLRpm(Binary):
    """
    Support for installing RPM files.
    - sources is a list of rpms
    - installation is with --nodeps (so the sources list has to be complete)
    """

    @staticmethod
    def extra_options(extra_vars=None):
        """Extra easyconfig parameters specific to RPMs."""
        extra_vars = Binary.extra_options(extra_vars)
        extra_vars.update({
            'force': [False, "Use force", CUSTOM],
            'preinstall': [False, "Enable pre install", CUSTOM],
            'postinstall': [False, "Enable post install", CUSTOM],
            'makesymlinks': [[], "Create symlinks for listed paths", CUSTOM],  # supports glob
        })
        return extra_vars

    def configure_step(self):
          return

    def install_step(self):
        """Custom installation procedure for RPMs into a custom prefix."""
        try:
            os.chdir(self.installdir)
            os.mkdir('rpm')
        except:
            self.log.error("Can't create rpm dir in install dir %s" % self.installdir)

        cmd = "rpm --initdb --dbpath /rpm --root %s" % self.installdir

        run_cmd(cmd, log_all=True, simple=True)

        force=''
        if self.cfg['force']:
            force = '--force'

        postinstall = '--nopost'
        if self.cfg['postinstall']:
            postinstall = ''
        preinstall = '--nopre'
        if self.cfg['preinstall']:
            preinstall = ''

        # exception for user root:
        # --relocate is not necesarry -> --root will relocate more than enough
        # cmd_tpl = "rpm -i --dbpath /rpm %(force)s --root %(inst)s %(pre)s %(post)s --nodeps %(rpm)s"

        for rpm in self.src:
            cmd = "rpm -qp --qf '%%{PREFIXES}' %s" % rpm['path']
            (prefix, _) = run_cmd(cmd, log_all=True, simple=False)
            #prefix='/'  # for those that don't have a Prefix: (needs work)
        
            cmd_tpl = "export XLCPPRTDB=%(inst)s/rpm ; rpm -iv --dbpath %(inst)s/rpm %(force)s --relocate %(prefix)s=%(inst)s --relocate /usr=%(inst)s --badreloc " \
                  "%(pre)s %(post)s --nodeps --ignorearch %(rpm)s"

            cmd = cmd_tpl % {
                'inst': self.installdir,
                'rpm': rpm['path'],
                'force': force,
                'pre': preinstall,
                'post': postinstall,
                'prefix': prefix,
            }
            run_cmd(cmd, log_all=True, simple=True)

        for path in self.cfg['makesymlinks']:
            # allow globs, always use first hit.
            # also verify links existince
            realdirs = glob.glob(path)
            if realdirs:
                if len(realdirs) > 1:
                    self.log.debug("More then one match found for symlink glob %s, using first (all: %s)" % (path, realdirs))
                os.symlink(realdirs[0], os.path.join(self.installdir, os.path.basename(path)))
            else:
                self.log.debug("No match found for symlink glob %s." % path)

    def make_module_req_guess(self):
        """Add common PATH/LD_LIBRARY_PATH paths found in RPMs to list of guesses."""

        guesses = super(XLRpm, self).make_module_req_guess()

        guesses.update({
                        'PATH': guesses.get('PATH', []) + ['usr/bin', 'sbin', 'usr/sbin'],
                        'LD_LIBRARY_PATH': guesses.get('LD_LIBRARY_PATH', []) + ['usr/lib', 'usr/lib64'],
                        'MANPATH': guesses.get('MANPATH', []) + ['usr/share/man'],
                       })

        return guesses

