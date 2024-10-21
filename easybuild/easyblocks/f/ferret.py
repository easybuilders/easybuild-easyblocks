##
# Copyright 2009-2024 Ghent University
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
@author: Samuel Moors (Vrije Universiteit Brussel (VUB))
"""


import os
from easybuild.tools import LooseVersion
import easybuild.tools.toolchain as toolchain
from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import apply_regex_substitutions, change_dir, copy_file
from easybuild.tools.modules import get_software_root


class EB_Ferret(ConfigureMake):
    """Support for building/installing Ferret."""

    def configure_step(self):
        """Configure Ferret build."""

        buildtype = "x86_64-linux"
        if LooseVersion(self.version) < LooseVersion("7.3"):
            change_dir('FERRET')

        if LooseVersion(self.version) >= LooseVersion("7.5"):
            deps = ['HDF5', 'netCDF-Fortran']
        else:
            deps = ['HDF5', 'netCDF', 'Java']

        for name in deps:
            if not get_software_root(name):
                raise EasyBuildError("%s module not loaded?", name)

        if LooseVersion(self.version) >= LooseVersion("7.3"):
            copy_file('external_functions/ef_utility/site_specific.mk.in',
                      'external_functions/ef_utility/site_specific.mk')
            copy_file('site_specific.mk.in', 'site_specific.mk')
            fns = [
                "site_specific.mk",
                "external_functions/ef_utility/site_specific.mk",
            ]
        else:
            fns = ["site_specific.mk"]

        regex_subs = [
            (r"^BUILDTYPE\s*=.*", "BUILDTYPE = %s" % buildtype),
            (r"^INSTALL_FER_DIR =.*", "INSTALL_FER_DIR = %s" % self.installdir),
        ]

        if LooseVersion(self.version) >= LooseVersion("7.5"):
            regex_subs.append((r"^(HDF5_LIBDIR\s*)=.*", r"\1 = %s/lib" % get_software_root('HDF5')))
            regex_subs.append((r"^(NETCDF_LIBDIR\s*)=.*", r"\1 = %s/lib" % get_software_root('netCDF-Fortran')))
        else:
            for name in deps:
                regex_subs.append((r"^(%s.*DIR\s*)=.*" % name.upper(), r"\1 = %s" % get_software_root(name)))

        if LooseVersion(self.version) >= LooseVersion("7.3"):
            regex_subs.extend([
                (r"^DIR_PREFIX =.*", "DIR_PREFIX = %s" % self.cfg['start_dir']),
                (r"^FER_LOCAL_EXTFCNS = $(FER_DIR)", "FER_LOCAL_EXTFCNS = $(INSTALL_FER_DIR)/libs"),
            ])

        if LooseVersion(self.version) >= LooseVersion("7.5"):
            comp_vars = {
                'CC': 'CC',
                'FC': 'FC',
            }

            for key, value in comp_vars.items():
                regex_subs.append((r"^(%s\s*)=.*" % key, r"\1= %s " % os.getenv(value)))

            if self.toolchain.comp_family() == toolchain.INTELCOMP:
                regex_subs.append((r"^(\s*LD\s*)=.*", r"\1 = %s -nofor-main " % os.getenv("FC")))

        for fn in fns:
            apply_regex_substitutions(fn, regex_subs)

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

        regex_subs = [(r"^(FFLAGS\s*=').*-m64 (.*)", r"\1%s \2" % os.getenv('FFLAGS'))]
        for key, value in comp_vars.items():
            regex_subs.append((r"^(%s\s*)=.*" % key, r"\1='%s'" % os.getenv(value)))

        x11_root = get_software_root('X11')
        if x11_root:
            regex_subs.append((r"^(LD_X11\s*)=.*", r"\1='-L%s/lib -lX11'" % x11_root))
        else:
            regex_subs.append((r"^(LD_X11\s*)=.*", r"\1='-L/usr/lib64/X11 -lX11'"))

        if LooseVersion(self.version) >= LooseVersion("7.3") and self.toolchain.comp_family() == toolchain.INTELCOMP:
            regex_subs.extend(sorted(gfort2ifort.items()))

        apply_regex_substitutions(fn, regex_subs)

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

        regex_subs = []
        for key, value in comp_vars.items():
            regex_subs.append((r"^(\s*%s\s*)=.*" % key, r"\1 = %s" % os.getenv(value)))

        if LooseVersion(self.version) >= LooseVersion("7.3"):
            flag_vars = {
                "CFLAGS": "CFLAGS",
                "FFLAGS": "FFLAGS",
                "PPLUS_FFLAGS": "FFLAGS",
            }
            for key, value in flag_vars.items():
                regex_subs.append((r"^(\s*%s\s*=).*-m64 (.*)" % key, r"\1%s \2" % os.getenv(value)))

            regex_subs.extend([
                (r"^(\s*LDFLAGS\s*=).*", r"\1 -fPIC %s -lnetcdff -lnetcdf -lhdf5_hl -lhdf5" % os.getenv("LDFLAGS")),
                (r"^(\s*)CDFLIB", r"\1NONEED"),
            ])

        if self.toolchain.comp_family() == toolchain.INTELCOMP:
            regex_subs.append((r"^(\s*LD\s*)=.*", r"\1 = %s -nofor-main" % os.getenv("F77")))
            for x in ["CFLAGS", "FFLAGS"]:
                regex_subs.append((r"^(\s*%s\s*=\s*\$\(CPP_FLAGS\)).*\\" % x, r"\1 %s \\" % os.getenv(x)))
            if LooseVersion(self.version) >= LooseVersion("7.3"):
                regex_subs.extend(sorted(gfort2ifort.items()))

                regex_subs.append((r"^(\s*MYDEFINES\s*=.*)\\", r"\1-DF90_SYSTEM_ERROR_CALLS \\"))

        for fn in fns:
            apply_regex_substitutions(fn, regex_subs)

        if LooseVersion(self.version) >= LooseVersion("7.3"):
            comp_vars = {
                'CC': 'CC',
                'LDFLAGS': 'LDFLAGS',
            }
            fn = 'gksm2ps/Makefile'

            regex_subs = [(r"^(\s*CFLAGS=\")-m64 (.*)", r"\1%s \2" % os.getenv('CFLAGS'))]
            for key, value in comp_vars.items():
                regex_subs.append((r"^(\s*%s)=.*" % key, r"\1='%s' \\" % os.getenv(value)))

            apply_regex_substitutions(fn, regex_subs)

    def sanity_check_step(self):
        """Custom sanity check for Ferret."""

        major_minor_version = '.'.join(self.version.split('.')[:2])
        if LooseVersion(self.version) >= LooseVersion("7.6"):
            major_minor_version += self.version.split('.')[2]

        custom_paths = {
            'files': ["bin/ferret_v%s" % major_minor_version],
            'dirs': [],
        }

        super(EB_Ferret, self).sanity_check_step(custom_paths=custom_paths)
