##
# Copyright 2013-2024 Ghent University
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
EasyBuild support for building and installing Qt, implemented as an easyblock

@author: Kenneth Hoste (Ghent University)
"""
import os
from easybuild.tools import LooseVersion

import easybuild.tools.environment as env
import easybuild.tools.toolchain as toolchain
from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import apply_regex_substitutions
from easybuild.tools.modules import get_software_root
from easybuild.tools.run import run_cmd_qa
from easybuild.tools.systemtools import get_cpu_architecture, get_glibc_version, get_shared_lib_ext
from easybuild.tools.systemtools import AARCH64, POWER


class EB_Qt(ConfigureMake):
    """
    Support for building and installing Qt.
    """

    @staticmethod
    def extra_options():
        extra_vars = {
            'check_qtwebengine': [False, "Make sure QtWebEngine components is installed", CUSTOM],
            'disable_advanced_kernel_features': [False, "Disable features that require a kernel > 3.15", CUSTOM],
            'platform': [None, "Target platform to build for (e.g. linux-g++-64, linux-icc-64)", CUSTOM],
        }
        extra_vars = ConfigureMake.extra_options(extra_vars)

        # allowing to specify prefix_opt doesn't make sense for Qt, since -prefix is hardcoded in configure_step
        del extra_vars['prefix_opt']

        return extra_vars

    def configure_step(self):
        """Configure Qt using interactive `configure` script."""

        self.cfg.update('configopts', '-release')

        platform = None
        comp_fam = self.toolchain.comp_family()
        if self.cfg['platform']:
            platform = self.cfg['platform']
        # if no platform is specified, try to derive it based on compiler in toolchain
        elif comp_fam in [toolchain.GCC]:  # @UndefinedVariable
            myarch = get_cpu_architecture()
            if myarch == AARCH64:
                platform = 'linux-g++'
            else:
                platform = 'linux-g++-64'
        elif comp_fam in [toolchain.INTELCOMP]:  # @UndefinedVariable
            if LooseVersion(self.version) >= LooseVersion('4'):
                platform = 'linux-icc-64'
            else:
                platform = 'linux-icc'
                # fix -fPIC flag (-KPIC is not correct for recent Intel compilers)
                qmake_conf = os.path.join('mkspecs', platform, 'qmake.conf')
                apply_regex_substitutions(qmake_conf, [('-KPIC', '-fPIC')])

        if platform:
            self.cfg.update('configopts', "-platform %s" % platform)
        else:
            raise EasyBuildError("Don't know which platform to set based on compiler family.")

        if LooseVersion(self.version) >= LooseVersion('5.8'):
            # Qt5 doesn't respect $CFLAGS, $CXXFLAGS and $LDFLAGS, but has equivalent compiler options,
            # e.g. QMAKE_CFLAGS; see https://doc.qt.io/qt-5/qmake-variable-reference.html#qmake-cc.
            # Since EasyBuild relies e.g. for --optarch on $CFLAGS, we need to
            # set the equivalent QMAKE_* configure options.
            # (see also https://github.com/easybuilders/easybuild-easyblocks/issues/1670)
            env_to_options = {
                'CC': 'QMAKE_CC',
                'CFLAGS': 'QMAKE_CFLAGS',
                'CXX': 'QMAKE_CXX',
                'CXXFLAGS': 'QMAKE_CXXFLAGS',
                # QMAKE_LFLAGS is not a typo, see: https://doc.qt.io/qt-5/qmake-variable-reference.html#qmake-lflags
                'LDFLAGS': 'QMAKE_LFLAGS',
            }
            for env_name, option in sorted(env_to_options.items()):
                value = os.getenv(env_name)
                if value is not None:
                    if env_name.endswith('FLAGS'):
                        # For *FLAGS, we add to existing flags (e.g. those set in Qt's .pro-files).
                        config_opt = option + '+="%s"'
                    else:
                        # For compilers, we replace QMAKE_CC/CXX
                        # (otherwise, you get e.g. QMAKE_CC="g++ g++", which fails)
                        config_opt = option + '="%s"'

                    self.cfg.update('configopts', config_opt % value)

        # configure Qt such that xmlpatterns is also installed
        # -xmlpatterns is not a known configure option for Qt 5.x, but there xmlpatterns support is enabled by default
        if LooseVersion(self.version) >= LooseVersion('4') and LooseVersion(self.version) < LooseVersion('5'):
            self.cfg.update('configopts', '-xmlpatterns')

        # disable specific features to avoid that libQt5Core.so being tagged as requiring kernel 3.17,
        # which causes confusing problems like this even though the file exists and can be found by...
        #     error while loading shared libraries: libQt5Core.so.5:
        #      cannot open shared object file: No such file or directory
        # see also:
        # * https://bugs.gentoo.org/669994
        # * https://github.com/NixOS/nixpkgs/commit/a7b6a9199e8db54a798d011a0946cdeb72cfc46b
        # * https://gitweb.gentoo.org/proj/qt.git/commit/?id=9ff0752e1ee3c28818197eaaca45545708035152
        kernel_version = os.uname()[2]
        skip_kernel_features = self.cfg['disable_advanced_kernel_features']
        old_kernel_version = LooseVersion(kernel_version) < LooseVersion('3.17')
        if LooseVersion(self.version) >= LooseVersion('5.10') and (skip_kernel_features or old_kernel_version):
            self.cfg.update('configopts', '-no-feature-renameat2')
            self.cfg.update('configopts', '-no-feature-getentropy')

        cmd = "%s ./configure -prefix %s %s" % (self.cfg['preconfigopts'], self.installdir, self.cfg['configopts'])
        qa = {
            "Type 'o' if you want to use the Open Source Edition.": 'o',
            "Do you accept the terms of either license?": 'yes',
            "Which edition of Qt do you want to use?": 'o',
        }
        no_qa = [
            "for .*pro",
            r"%s.*" % os.getenv('CXX', '').replace('+', '\\+'),  # need to escape + in 'g++'
            "Reading .*",
            "WARNING .*",
            "Project MESSAGE:.*",
            "rm -f .*",
            'Creating qmake...',
            'Checking for .*...',
        ]
        run_cmd_qa(cmd, qa, no_qa=no_qa, log_all=True, simple=True, maxhits=120)

        # Ninja uses all visible cores by default, which can lead to lack of sufficient memory;
        # so $NINJAFLAGS is set to control number of parallel processes used by Ninja;
        # note that $NINJAFLAGS is not a generic thing for Ninja, it's very specific to the Qt5 build procedure
        if LooseVersion(self.version) >= LooseVersion('5'):
            if get_software_root('Ninja'):
                env.setvar('NINJAFLAGS', '-j%s' % self.cfg['parallel'])

    def build_step(self):
        """Set $LD_LIBRARY_PATH before calling make, to ensure that all required libraries are found during linking."""
        # cfr. https://elist.ornl.gov/pipermail/visit-developers/2011-September/010063.html

        if LooseVersion(self.version) >= LooseVersion('5.6'):
            libdirs = ['qtbase', 'qtdeclarative']
        else:
            libdirs = ['']

        libdirs = [os.path.join(self.cfg['start_dir'], d, 'lib') for d in libdirs]
        self.cfg.update('prebuildopts', 'LD_LIBRARY_PATH=%s' % os.pathsep.join(libdirs + ['$LD_LIBRARY_PATH']))

        super(EB_Qt, self).build_step()

    def sanity_check_step(self):
        """Custom sanity check for Qt."""

        shlib_ext = get_shared_lib_ext()

        if LooseVersion(self.version) >= LooseVersion('4'):
            libversion = ''
            if LooseVersion(self.version) >= LooseVersion('5'):
                libversion = self.version.split('.')[0]

            libfile = os.path.join('lib', 'libQt%sCore.%s' % (libversion, shlib_ext))

        else:
            libfile = os.path.join('lib', 'libqt.%s' % shlib_ext)

        custom_paths = {
            'files': ['bin/moc', 'bin/qmake', libfile],
            'dirs': ['include', 'plugins'],
        }

        if self.cfg['check_qtwebengine']:
            glibc_version = get_glibc_version()
            myarch = get_cpu_architecture()
            if LooseVersion(glibc_version) <= LooseVersion("2.16"):
                self.log.debug("Skipping check for qtwebengine, since it requires a more recent glibc.")
            elif myarch == POWER:
                self.log.debug("Skipping check for qtwebengine, since it is not supported on POWER.")
            else:
                qtwebengine_libs = ['libQt%s%s.%s' % (libversion, x, shlib_ext) for x in ['WebEngine', 'WebEngineCore']]
                custom_paths['files'].extend([os.path.join('lib', lib) for lib in qtwebengine_libs])

        if LooseVersion(self.version) >= LooseVersion('4'):
            custom_paths['files'].append('bin/xmlpatterns')

        super(EB_Qt, self).sanity_check_step(custom_paths=custom_paths)
