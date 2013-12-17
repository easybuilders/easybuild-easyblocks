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
EasyBuild support for building and installing Python, implemented as an easyblock

@author: Stijn De Weirdt (Ghent University)
@author: Dries Verdegem (Ghent University)
@author: Kenneth Hoste (Ghent University)
@author: Pieter De Baets (Ghent University)
@author: Jens Timmerman (Ghent University)
"""

import os
from distutils.version import LooseVersion

from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import run_cmd


EXTS_FILTER_PYTHON_PACKAGES = ('python -c "import %(ext_name)s"', "")


class EB_Python(ConfigureMake):
    """Support for building/installing Python
    - default configure/build_step/make install works fine

    To extend Python by adding extra packages there are two ways:
    - list the packages in the exts_list, this will include the packages in this Python installation
    - create a seperate easyblock, so the packages can be loaded with module load

    e.g., you can include numpy and scipy in a default Python installation
    but also provide newer updated numpy and scipy versions by creating a PythonPackage-derived easyblock for it.
    """

    def prepare_for_extensions(self):
        """
        Set default class and filter for Python packages
        """
        # build and install additional packages with PythonPackage easyblock
        self.cfg['exts_defaultclass'] = "PythonPackage"
        self.cfg['exts_filter'] = EXTS_FILTER_PYTHON_PACKAGES

    def configure_step(self):
        """Set extra configure options."""
        self.cfg.update('configopts', "--with-threads --enable-shared")

        super(EB_Python, self).configure_step()

    def install_step(self):
        """Extend make install to make sure that the 'python' command is present."""
        super(EB_Python, self).install_step()

        python_binary_path = os.path.join(self.installdir, 'bin', 'python')
        if not os.path.isfile(python_binary_path):
            pythonver = '.'.join(self.version.split('.')[0:2])
            srcbin = "%s%s" % (python_binary_path, pythonver)
            try:
                os.symlink(srcbin, python_binary_path)
            except OSError, err:
                self.log.error("Failed to symlink %s to %s: %s" % err)

    def sanity_check_step(self):
        """Custom sanity check for Python."""

        pyver = "python%s" % '.'.join(self.version.split('.')[0:2])

        try:
            fake_mod_data = self.load_fake_module()
        except EasyBuildError, err:
            self.log.error("Loading fake module failed: %s" % err)

        abiflags = ''
        if LooseVersion(self.version) >= LooseVersion("3"):
            run_cmd("which python", log_all=True, simple=False)
            cmd = 'python -c "import sysconfig; print(sysconfig.get_config_var(\'abiflags\'));"'
            (abiflags, _) = run_cmd(cmd, log_all=True, simple=False)
            if not abiflags:
                self.log.error("Failed to determine abiflags: %s" % abiflags)
            else:
                abiflags = abiflags.strip()

        custom_paths = {
            'files': ["bin/%s" % pyver, "lib/lib%s%s.so" % (pyver, abiflags)],
            'dirs': ["include/%s%s" % (pyver, abiflags), "lib/%s" % pyver]
        }

        # make sure that ctypes are actually working, this is needed for a lot of dependencies
        custom_commands = [('python', '-c "import _ctypes"')]

        # cleanup
        self.clean_up_fake_module(fake_mod_data)

        super(EB_Python, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)
