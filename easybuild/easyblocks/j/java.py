##
# Copyright 2012-2025 Ghent University
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
EasyBlock for installing Java, implemented as an easyblock

@author: Jens Timmerman (Ghent University)
@author: Kenneth Hoste (Ghent University)
"""
import os
import stat

from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools import LooseVersion
from easybuild.easyblocks.generic.packedbinary import PackedBinary
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import adjust_permissions, change_dir, copy_dir, copy_file, remove_dir, remove_file
from easybuild.tools.run import run_cmd
from easybuild.tools.systemtools import AARCH64, POWER, RISCV64, X86_64, get_cpu_architecture


class EB_Java(PackedBinary):
    """Support for installing Java as a packed binary file (.tar.gz)
    Use the PackedBinary easyblock and set some extra paths.
    """
    # List of AWT and related libraries, relative to the %(installdir)/lib
    AWT_LIBS = ['libawt.so', 'libawt_headless.so', 'libawt_xawt.so', 'libfontmanager.so', 'libjawt.so', 'liblcms.so',
                'libsplashscreen.so', 'libjsound.so']

    @staticmethod
    def extra_options(extra_vars=None):
        """Extra easyconfig parameters specific to Java easyblock."""
        extra_vars = PackedBinary.extra_options(extra_vars)
        extra_vars.update({
            # Overwrite the default value for run_rpath_sanity_check to True, since we have RPATH patching with
            # patchelf for Java
            'run_rpath_sanity_check': [True, "Whether or not to run the RPATH sanity check", CUSTOM],
            'patch_rpaths': [True, "Whether or not to use patchelf to add relevant dirs (from LIBRARY_PATH or, "
                                   "if sysroot is enabled, from default libdirs in the sysroot) to RPATH", CUSTOM],
            'extra_rpaths': [['%(installdir)s/lib/server'],
                             "List of directories to add to the RPATH, aside from the "
                             "default ones added by patch_rpaths. Any $EBROOT* environment variables will be "
                             "replaced by their respective values before setting the RPATH.", CUSTOM],
            'patch_interpreter': [True, "Whether or not to use patchelf to patch the interpreter in executables when "
                                        "sysroot is used", CUSTOM],
            # Also patch shared libraries in lib/server by default
            'bin_lib_subdirs': [['bin', 'lib', 'lib/server'],
                                "List of subdirectories for binaries and libraries, which is used "
                                "during sanity check to check RPATH linking and banned/required libraries", CUSTOM],
            'exclude_awt_libs': [True, "Whether or to exclude the awt (and related) libraries from being installed ",
                                 CUSTOM],
        })
        return extra_vars

    def __init__(self, *args, **kwargs):
        """ Init the Java easyblock adding a new jdkarch template var """
        myarch = get_cpu_architecture()
        if myarch == AARCH64:
            jdkarch = 'aarch64'
        elif myarch == POWER:
            jdkarch = 'ppc64le'
        elif myarch == RISCV64:
            jdkarch = 'riscv64'
        elif myarch == X86_64:
            jdkarch = 'x64'
        else:
            raise EasyBuildError("Architecture %s is not supported for Java on EasyBuild", myarch)

        super(EB_Java, self).__init__(*args, **kwargs)

        self.cfg.template_values['jdkarch'] = jdkarch
        self.cfg.generate_template_values()

    def extract_step(self):
        """Unpack the source"""
        if LooseVersion(self.version) < LooseVersion('1.7'):

            copy_file(self.src[0]['path'], self.builddir)
            adjust_permissions(os.path.join(self.builddir, self.src[0]['name']), stat.S_IXUSR, add=True)

            change_dir(self.builddir)
            run_cmd(os.path.join(self.builddir, self.src[0]['name']), log_all=True, simple=True, inp='')
        else:
            PackedBinary.extract_step(self)
            adjust_permissions(self.builddir, stat.S_IWUSR, add=True, recursive=True)

    def install_step(self):
        """Custom install step: just copy unpacked installation files."""
        if LooseVersion(self.version) < LooseVersion('1.7'):
            remove_dir(self.installdir)
            copy_dir(os.path.join(self.builddir, 'jdk%s' % self.version), self.installdir)
        else:
            PackedBinary.install_step(self)
        if self.cfg.get('exclude_awt_libs', True):
            # Remove AWT and related libraries, so we can install those at GCCcore level
            # and provide those with the necessary dependencies
            # Separating those enables us to keep the core Java at system toolchain level
            # See https://github.com/easybuilders/easybuild-easyconfigs/pull/22245#issuecomment-2635560327
            self.log.info("Stripping awt and related libraries from Java installation")
            for lib in self.AWT_LIBS:
                filename = os.path.join(self.installdir, 'lib', lib)
                self.log.debug("Removing %s" % filename)
                remove_file(filename)

    def sanity_check_step(self):
        """Custom sanity check for Java."""
        custom_paths = {
            'files': ['bin/java', 'bin/javac'],
            'dirs': ['lib'],
        }

        custom_commands = [
            "java -help",
            "javac -help",
        ]

        super(EB_Java, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)

    def make_module_extra(self):
        """
        Set $JAVA_HOME to installation directory
        """
        txt = PackedBinary.make_module_extra(self)
        txt += self.module_generator.set_environment('JAVA_HOME', self.installdir)
        return txt
