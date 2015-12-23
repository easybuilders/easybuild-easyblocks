##
# Copyright 2013 Ghent University
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
EasyBuild support for building and installing CPMD, implemented as an easyblock

@author: Benjamin Roberts (Landcare Research NZ Ltd) 
"""

from distutils.version import LooseVersion
import fileinput
import glob
import os
import platform
import re
import shutil
import sys

from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
import easybuild.tools.environment as env
from easybuild.tools.modules import get_software_root, get_software_version
from easybuild.tools.run import run_cmd
from easybuild.tools.systemtools import get_os_type
import easybuild.tools.toolchain as toolchain

class EB_CPMD(ConfigureMake):
    """
    Support for building CPMD
    """

    @staticmethod
    def extra_options():
        """Custom easyconfig parameters for CPMD."""
        extra_vars = {
            'base_configuration': [None, "Base configuration from which to start (file name)", CUSTOM],
        }
        return ConfigureMake.extra_options(extra_vars)

    def prepare_step(self):
        super(EB_CPMD, self).prepare_step()

        # create install directory and make sure it does not get cleaned up again in the install step;
        # the first configure iteration already puts things in place in the install directory,
        # so that shouldn't get cleaned up afterwards...
        self.log.info("Creating install dir %s before starting configure-build-install iterations", self.installdir)
        self.make_installdir()
        self.cfg['keeppreviousinstall'] = True

    def configure_step(self, cmd_prefix=''):
        """
        Configure step
        """

        config_file_candidates = []
        config_file_prefix = os.path.join(self.builddir, "CPMD", "configure")

        # Work out a starting configuration file if one is not supplied in the easyconfig
        if self.cfg['base_configuration']:
            config_file_base = self.cfg['base_configuration']
        else:
            os_type_mappings = {
                                "LINUX"  : "LINUX",
                                "DARWIN" : "MACOSX",
                                }
            os_type = os_type_mappings[get_os_type().upper()]
            machine = ""
            if os_type != "MACOSX":
                machine = platform.machine().upper()
       
            config_file_base = os_type
            if len(machine) > 0:
                config_file_base += "-" + machine
            
            if self.toolchain.comp_family() in [toolchain.INTELCOMP]:
                config_file_base += "-INTEL"

            # enable MPI support if desired
            if self.toolchain.options.get('usempi', None):
                config_file_base += "-MPI"
           
            # Note that the -FFTW and -FFTW3 options are always at the end
            # of the configuration file name, so this block needs to come
            # last within the "else".
            # Also, only version 3 or greater of FFTW is useful for CPMD.
            if get_software_root('imkl') or (get_software_root('FFTW') and LooseVersion(get_software_version('FFTW')) >= LooseVersion('3.0')):
                config_file_base += "-FFTW"
                config_file_candidates.append(config_file_base + "3")

        config_file_candidates.append(config_file_base)

        selected_base_config = None
        selected_full_config = None
        for cfc in config_file_candidates:
            self.log.info("Trying configuration file: %s", cfc)
            config_file_full = os.path.join(config_file_prefix, cfc)
            if os.path.isfile(config_file_full):
                selected_base_config = cfc
                selected_full_config = config_file_full
                self.log.info("Selected %s as base configuration file", cfc)
                break

        if selected_base_config is None:
            raise EasyBuildError("Base configuration file does not exist. Please edit base_configuration or review the CPMD easyblock.")

        try:
            for line in fileinput.input(selected_full_config, inplace=1, backup='.orig'):
                if self.toolchain.comp_family() in [toolchain.INTELCOMP]:
                    ar_exe = "xiar -ruv"
                    line = re.sub(r"^(\s*AR)=.*", r"\1='%s'" % ar_exe, line)
                # Better to get CC and FC from the EasyBuild environment
                # in this instance
                line = re.sub(r"^(\s*CC=.*)",     r"#\1",        line)
                line = re.sub(r"^(\s*FC=.*)",     r"#\1",        line)
                #line = re.sub(r"^(\s*CFLAGS=)'?((?!\W-g\W)[^']*)'?\s*$", r"\1'{0}\2 '".format(os.getenv('CFLAGS')), line)
                line = re.sub(r"^(\s*LD)=.*",     r"\1='$(FC)'", line)
                sys.stdout.write(line)
        except IOError, err:
            raise EasyBuildError("Failed to patch %s: %s", selected_base_config, err)

        if self.cfg['configure_cmd_prefix']:
            if cmd_prefix:
                tup = (cmd_prefix, self.cfg['configure_cmd_prefix'])
                self.log.debug("Specified cmd_prefix '%s' is overruled by configure_cmd_prefix '%s'" % tup)
            cmd_prefix = self.cfg['configure_cmd_prefix']

        if self.cfg['tar_config_opts']:
            # setting am_cv_prog_tar_ustar avoids that configure tries to figure out
            # which command should be used for tarring/untarring
            # am__tar and am__untar should be set to something decent (tar should work)
            tar_vars = {
                'am__tar': 'tar chf - "$$tardir"',
                'am__untar': 'tar xf -',
                'am_cv_prog_tar_ustar': 'easybuild_avoid_ustar_testing'
            }
            for (key, val) in tar_vars.items():
                self.cfg.update('preconfigopts', "%s='%s'" % (key, val))

        options = [self.cfg['configopts']]

        # enable OpenMP support if desired
        if self.toolchain.options.get('openmp', None):
            options.append("-omp")

        # This "option" has to come last as it's the chief argument, coming after
        # all flags and so forth.
        options.append(selected_base_config)

        cmd = "%(preconfigopts)s %(cmd_prefix)s./configure.sh %(prefix_opt)s%(installdir)s %(configopts)s" % {
            'preconfigopts': self.cfg['preconfigopts'],
            'cmd_prefix': cmd_prefix,
            'prefix_opt': self.cfg['prefix_opt'],
            'installdir': self.installdir,
            'configopts': ' '.join(options)
        }

        (out, _) = run_cmd(cmd, log_all=True, simple=False)

        return out

    def build_step(self):

        os.chdir(self.installdir)
        super(EB_CPMD, self).build_step()

    # No need for a separate install step as the software is built in situ.
    # In fact, an install step throws away the entire package.
    def install_step(self):
        pass
