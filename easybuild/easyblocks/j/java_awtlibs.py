##
# Copyright 2012-2024 Ghent University
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
from easybuild.easyblocks.j.java import EB_Java
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import adjust_permissions, change_dir, copy_dir, copy_file, remove
from easybuild.tools.run import run_cmd
from easybuild.tools.systemtools import AARCH64, POWER, RISCV64, X86_64, get_cpu_architecture


class EB_Java_minus_awtlibs(EB_Java):
    """Support for installing the Java awt libraries if they are stripped from the Java installation"""

    @staticmethod
    def extra_options(extra_vars=None):
        """Extra easyconfig parameters specific to Java easyblock."""
        extra_vars = EB_Java.extra_options(extra_vars)
        extra_vars.update({
            # We inherit from Java, so we set change the default to False here, since clearly, we want the awt libs!
            # This is important, since we call the install_step from Java before stripping anytything non-awt related
            'exclude_awt_libs': [False, "Whether or to exclude the awt (and related) libraries from being installed ",
                                 CUSTOM],
            # libjvm.so isn't on library path, as it is in $EBROOTJAVA/lib/server
            # So, make sure this is on the default extra_rpaths for Java-awtlibs
            'extra_rpaths': [['$EBROOTJAVA/lib/server'], "List of directories to add to the RPATH, aside from the "
                             "default ones added by patch_rpaths. Any $EBROOT* environment variables will be replaced "
                             "by their respective values before setting the RPATH.", CUSTOM],
        })
        return extra_vars

    def install_step(self):
        """Custom install step: just copy unpacked installation files."""
        super(EB_Java_minus_awtlibs, self).install_step()
        self.log.info("Removing all files and directories that are not part of the AWT libs")
        # Now, strip everything that is NOT in lib or lib64
        self.log.debug("Remove everything not in %s/lib or %s/lib64", self.installdir, self.installdir)
        for path in os.listdir(self.installdir):
            if path != 'lib' and path != 'lib64':
                full_path = os.path.join(self.installdir, path)
                self.log.debug("Removing %s" % full_path)
                remove(full_path)

        # Then, strip everything from lib and lib64 that is not in self.AWT_LIBS
        self.log.debug("Remove everything from %s/lib that is not AWT related", self.installdir)
        libdir = os.path.join(self.installdir, 'lib')
        if os.path.isdir(libdir):
            for path in os.listdir(libdir):
                if path not in EB_Java.AWT_LIBS:
                    full_path = os.path.join(self.installdir, 'lib', path)
                    self.log.debug("Removing %s" % full_path)
                    remove(full_path)

    def sanity_check_step(self):
        """Custom sanity check for Java."""
        custom_paths = {
            'files': ['lib/%s' % libname for libname in EB_Java.AWT_LIBS],
            'dirs': [],
        }
        custom_commands = []
        # Don't call Java's sanity_check_step, but the packed-binary one. Otherwise, these would just be overwritten again
        super(EB_Java, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)

    def make_module_extra(self):
        """
        Make sure this does not set JAVA_HOME, even though we inherit from the Java easyblock
        """
        txt = PackedBinary.make_module_extra(self)
        return txt
