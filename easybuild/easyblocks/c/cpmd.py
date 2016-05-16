##
# Copyright 2016 Landcare Research NZ Ltd
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
from easybuild.tools.filetools import apply_regex_substitutions
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

        for confdirname in ["configure", "CONFIGURE"]:
            config_file_prefix = os.path.join(self.builddir, "CPMD", confdirname)
            if os.path.isdir(config_file_prefix):
                break
        else:
            raise EasyBuildError("No directory containing configuration files. Please review source tarball contents, and amend the EasyBlock if necessary")

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
            apply_regex_substitutions(selected_full_config, [
                # Better to get CC and FC from the EasyBuild environment in this instance
                (r"^(\s*CC=.*)", r"#\1"),
                (r"^(\s*FC=.*)", r"#\1"),
                (r"^(\s*LD)=.*", r"\1='$(FC)'"),
            ])
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
        if self.toolchain.options.get('openmp', None) and LooseVersion(self.version) >= LooseVersion('4.0'):
            options.append("-omp")

        # This "option" has to come last as it's the chief argument, coming after
        # all flags and so forth.
        options.append(selected_base_config)

        # I'm not sure when mkconfig.sh changed to configure.sh. Assuming 4.0
        # for the sake of the argument.
        if LooseVersion(self.version) >= LooseVersion('4.0'):
            config_exe = 'configure.sh'
        else:
            config_exe = 'mkconfig.sh'
            options.append('-BIN={0}'.format(os.path.join(self.installdir, "bin")))
            options.append('>')
            options.append(os.path.join(self.installdir, "Makefile"))

        cmd = "%(preconfigopts)s %(cmd_prefix)s./%(config_exe)s %(prefix_opt)s%(installdir)s %(configopts)s" % {
            'preconfigopts': self.cfg['preconfigopts'],
            'cmd_prefix': cmd_prefix,
            'config_exe': config_exe,
            'prefix_opt': self.cfg['prefix_opt'],
            'installdir': self.installdir,
            'configopts': ' '.join(options),
        }

        (out, _) = run_cmd(cmd, log_all=True, simple=False)

        return out

    def build_step(self):

        """
        Make some changes to files in order to make the build process more EasyBuild-friendly
        """
        os.chdir(self.installdir)
        if LooseVersion(self.version) < LooseVersion('4.0'):
            os.mkdir("bin")
        # Master configure script
        makefile = os.path.join(self.installdir, "Makefile")
        try:
            apply_regex_substitutions(makefile, [
                (r"^(\s*LFLAGS\s*=.*[^\w-])-L/usr/lib64/atlas/([^\w-].*)$", r"\1\2"),
                (r"^(\s*LFLAGS\s*=.*[^\w-])-llapack([^\w-].*)$", r"\1\2"),
                (r"^(\s*LFLAGS\s*=.*[^\w-])-lblas([^\w-].*)$", r"\1\2"),
                (r"^(\s*LFLAGS\s*=.*[^\w-])-lfftw([^\w-].*)$", r"\1\2"),
            ])
            if self.toolchain.comp_family() in [toolchain.INTELCOMP]:
                ar_exe = "xiar -ruv"
                apply_regex_substitutions(makefile, [
                    (r"^(\s*AR\s*=).*", r"\1 {0}".format(ar_exe))
                ])
                if LooseVersion(self.version) < LooseVersion('4.0'):
                    apply_regex_substitutions(makefile, [
                        (r"^(\s*CFLAGS\s*=.*[^\w-])-O2([^\w-].*)$", r"\1\2"),
                        (r"^(\s*CFLAGS\s*=.*[^\w-])-Wall([^\w-].*)$", r"\1\2"),
                        (r"^(\s*CPPFLAGS\s*=.*[^\w-])-D__PGI([^\w-].*)$", r"\1\2"),
                        (r"^(\s*CPPFLAGS\s*=.*[^\w-])-D__GNU([^\w-].*)$", r"\1\2"),
                        (r"^(\s*FFLAGS\s*=.*[^\w-])-O2([^\w-].*)$", r"\1\2"),
                        (r"^(\s*FFLAGS\s*=.*[^\w-])-fcray-pointer([^\w-].*)$", r"\1\2"),
                    ])
            apply_regex_substitutions(makefile, [
                (r"^(\s*CPPFLAGS\s*=.*)", r"\1 {0}".format(os.getenv('CPPFLAGS'))),
                (r"^(\s*CFLAGS\s*=.*)",   r"\1 {0}".format(os.getenv('CFLAGS'))),
                (r"^(\s*FFLAGS\s*=.*)",   r"\1 {0}".format(os.getenv('FFLAGS'))),
                (r"^(\s*LFLAGS\s*=.*)",   r"\1 {0}".format(os.getenv('LDFLAGS'))),
            ])
            if self.toolchain.options.get('openmp', None):
                apply_regex_substitutions(makefile, [
                    (r"^(\s*LFLAGS\s*=.*)",   r"\1 {0} {1}".format(os.getenv('LIBLAPACK_MT'), os.getenv('LIBBLAS_MT')))
                ])
            else:
                apply_regex_substitutions(makefile, [
                    (r"^(\s*LFLAGS\s*=.*)",   r"\1 {0} {1}".format(os.getenv('LIBLAPACK'), os.getenv('LIBBLAS')))
                ])
            apply_regex_substitutions(makefile, [
                (r"^(\s*LFLAGS\s*=.*)",   r"\1 {0}".format(os.getenv('LIBFFT'))),
            ])

            if get_software_root('imkl'):
                if LooseVersion(self.version) < LooseVersion('4.0'):
                    apply_regex_substitutions(makefile, [
                        (r"(\s+)-DFFT_FFTW(\s+)", r"\1-DFFT_DEFAULT -DINTEL_MKL\2"),
                    ])
            if LooseVersion(self.version) >= LooseVersion('4.0'):
                apply_regex_substitutions(makefile, [
                    (r"^(\s*CC\s*=.*)",       r"#\1"),
                    (r"^(\s*FC\s*=.*)",       r"#\1"),
                ])
        except IOError, err:
            raise EasyBuildError("Failed to patch %s: %s", makefile, err)

        super(EB_CPMD, self).build_step()

    # No need for a separate install step as the software is built in situ.
    # In fact, an install step throws away the entire package.
    def install_step(self):
        pass
