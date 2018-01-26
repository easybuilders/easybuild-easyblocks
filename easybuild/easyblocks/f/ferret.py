##
# Copyright 2009-2018 Ghent University
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://www.vscentrum.be),
# Flemish Research Foundation (FWO) (http://www.fwo.be/en)
# and the Department of Economy, Science and Innovation (EWI) (http://www.ewi-vlaanderen.be/en).
#
# https://github.com/easybuilders/easybuild
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
EasyBuild support for building and installing Ferret, implemented as an easyblock

@author: Stijn De Weirdt (Ghent University)
@author: Dries Verdegem (Ghent University)
@author: Kenneth Hoste (Ghent University)
@author: Pieter De Baets (Ghent University)
@author: Jens Timmerman (Ghent University)
@author: George Fanourgakis (The Cyprus Institute)
"""


import fileinput
import os
import re
import shutil
import sys
from distutils.version import LooseVersion
import easybuild.tools.toolchain as toolchain
from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.modules import get_software_root


class EB_Ferret(ConfigureMake):
    """Support for building/installing Ferret."""

    def configure_step(self):
        """Configure Ferret build."""

        buildtype = "x86_64-linux"
        if LooseVersion(self.version) < LooseVersion("7.3"):
            try:
                os.chdir('FERRET')
            except OSError, err:
                raise EasyBuildError("Failed to change to FERRET dir: %s", err)

        deps = ['HDF5', 'netCDF', 'Java']

        for name in deps:
            if not get_software_root(name):
                raise EasyBuildError("%s module not loaded?", name)

        if LooseVersion(self.version) >= LooseVersion("7.3"):
            try:
                shutil.copy2('external_functions/ef_utility/site_specific.mk.in',
                             'external_functions/ef_utility/site_specific.mk')
                shutil.copy2('site_specific.mk.in', 'site_specific.mk')
            except OSError, err:
                raise EasyBuildError("Failed to copy external_functions/ef_utility/site_specific.mk.in " +
                                     "to external_functions/ef_utility/site_specific.mk or site_specific.mk.in " +
                                     "to site_specific.mk: %s", err)
            fns = [
                "site_specific.mk",
                "external_functions/ef_utility/site_specific.mk",
            ]
        else:
            fns = "site_specific.mk"

        for fn in fns:
            for line in fileinput.input(fn, inplace=1, backup='.orig'):
                line = re.sub(r"^BUILDTYPE\s*=.*", "BUILDTYPE = %s" % buildtype, line)
                line = re.sub(r"^INSTALL_FER_DIR =.*", "INSTALL_FER_DIR = %s" % self.installdir, line)

                for name in deps:
                    line = re.sub(r"^(%s.*DIR\s*)=.*" % name.upper(), r"\1 = %s" % get_software_root(name), line)

                if LooseVersion(self.version) >= LooseVersion("7.3"):
                    line = re.sub(r"^DIR_PREFIX =.*", "DIR_PREFIX = %s" % self.cfg['start_dir'], line)
                    line = re.sub(r"^FER_LOCAL_EXTFCNS = $(FER_DIR)",
                                  "FER_LOCAL_EXTFCNS = $(INSTALL_FER_DIR)/libs", line)

                sys.stdout.write(line)

        comp_vars = {
            'CC': 'CC',
            'CFLAGS': 'CFLAGS',
            'CPPFLAGS': 'CPPFLAGS',
            'FC': 'F77',
        }

        gfort2ifort = {
            '-fno-second-underscore': ' ',
            '-fno-backslash': ' ',
            '-fdollar-ok': ' ',
            '-ffast-math': ' ',
            '-ffixed-line-length-132': '-132',
            '-fno-automatic': ' ',
            '-ffpe-trap=overflow': ' ',
            '-fimplicit-none': '-implicitnone',
            '-fdefault-real-8': '-r8',
            '-fdefault-double-8': ' ',
            '-Wl,-Bstatic -lgfortran -Wl,-Bdynamic': ' ',
            '-v --verbose -m64': ' ',
            '-export-dynamic': ' ',
            '-DG77_SIGNAL': ' ',
        }

        fn = 'xgks/CUSTOMIZE.%s' % buildtype

        for line in fileinput.input(fn, inplace=1, backup='.orig'):

            for x, y in comp_vars.items():
                line = re.sub(r"^(%s\s*)=.*" % x, r"\1='%s'" % os.getenv(y), line)

            line = re.sub(r"^(FFLAGS\s*=').*-m64 (.*)", r"\1%s \2" % os.getenv('FFLAGS'), line)
            if LooseVersion(self.version) >= LooseVersion("7.3"):
                line = re.sub(r"^(LD_X11\s*)=.*", r"\1='-L$(EBROOTX11)/lib -lX11'", line)
            else:
                line = re.sub(r"^(LD_X11\s*)=.*", r"\1='-L/usr/lib64/X11 -lX11'", line)

            if LooseVersion(self.version) >= LooseVersion("7.3"):
                if self.toolchain.comp_family() == toolchain.INTELCOMP:
                    for x, y in gfort2ifort.items():
                        line = re.sub(r"%s" % x, r"%s" % y, line)

            sys.stdout.write(line)

        comp_vars = {
            'CC': 'CC',
            'CXX': 'CXX',
            'F77': 'F77',
            'FC': 'F77',
        }

        if LooseVersion(self.version) >= LooseVersion("7.3"):
            fns = [
                'platform_specific.mk.%s' % buildtype,
                'external_functions/ef_utility/platform_specific.mk.%s' % buildtype,
            ]
        else:
            fns = [
                'fer/platform_specific_flags.mk.%s' % buildtype,
                'ppl/platform_specific_flags.mk.%s' % buildtype,
                'external_functions/ef_utility/platform_specific_flags.mk.%s' % buildtype,
            ]

        for fn in fns:
            for line in fileinput.input(fn, inplace=1, backup='.orig'):
                for x, y in comp_vars.items():
                    line = re.sub(r"^(\s*%s\s*)=.*" % x, r"\1 = %s" % os.getenv(y), line)

                if LooseVersion(self.version) >= LooseVersion("7.3"):
                    line = re.sub(r"^(\s*LDFLAGS\s*=).*",
                                  r"\1 -fPIC %s -lnetcdff -lnetcdf -lhdf5_hl -lhdf5" % os.getenv("LDFLAGS"), line)
                    line = re.sub(r"^(\s*)CDFLIB", r"\1NONEED", line)
                if self.toolchain.comp_family() == toolchain.INTELCOMP:
                    line = re.sub(r"^(\s*LD\s*)=.*", r"\1 = %s -nofor-main" % os.getenv("F77"), line)
                    for x in ["CFLAGS", "FFLAGS"]:
                        line = re.sub(r"^(\s*%s\s*=\s*\$\(CPP_FLAGS\)).*\\" % x, r"\1 %s \\" % os.getenv(x), line)
                    if LooseVersion(self.version) >= LooseVersion("7.3"):
                        for x in ["CFLAGS", "FFLAGS"]:
                            line = re.sub(r"^(\s*%s\s*=).*-m64 (.*)" % x, r"\1%s \2" % os.getenv(x), line)
                        for x, y in gfort2ifort.items():
                            line = re.sub(r"%s" % x, r"%s" % y, line)

                        line = re.sub(r"^(\s*MYDEFINES\s*=.*)\\", r"\1-DF90_SYSTEM_ERROR_CALLS \\", line)

                sys.stdout.write(line)

        if LooseVersion(self.version) >= LooseVersion("7.3"):
            comp_vars = {
                'CC': 'CC',
                'LDFLAGS': 'LDFLAGS',
            }
            fn = 'gksm2ps/Makefile'

            for line in fileinput.input(fn, inplace=1, backup='.orig'):
                for x, y in comp_vars.items():
                    line = re.sub(r"^(\s*%s)=.*" % x, r"\1='%s' \\" % os.getenv(y), line)

                line = re.sub(r"^(\s*CFLAGS=\")-m64 (.*)", r"\1%s \2" % os.getenv('CFLAGS'), line)

                sys.stdout.write(line)

    def sanity_check_step(self):
        """Custom sanity check for Ferret."""

        custom_paths = {
            'files': ["bin/ferret_v%s" % self.version],
            'dirs': [],
        }

        super(EB_Ferret, self).sanity_check_step(custom_paths=custom_paths)
