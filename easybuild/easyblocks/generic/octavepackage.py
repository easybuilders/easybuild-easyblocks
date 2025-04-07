##
# Copyright 2009-2025 Ghent University
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
EasyBuild support for building and installing Octave, implemented as an easyblock

@author: Lekshmi Deepu (Juelich Supercomputing Centre)
@author: Kenneth Hoste (Ghent University)
"""
import os
import tempfile

from easybuild.framework.extensioneasyblock import ExtensionEasyBlock
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import change_dir
from easybuild.tools.run import run_shell_cmd


class OctavePackage(ExtensionEasyBlock):
    """Builds and installs Octave extension toolboxes."""

    def configure_step(self):
        """Raise error when configure step is run: installing Octave toolboxes stand-alone is not supported (yet)"""
        raise EasyBuildError("Installing Octave toolboxes stand-alone is not supported (yet)")

    def install_extension(self):
        """Perform Octave package installation (as extension)."""

        # if patches are specified, we need to unpack the source tarball, apply the patch,
        # and create a temporary tarball to use for installation
        if self.patches:
            # call out to ExtensionEasyBlock to unpack & apply patches
            super(OctavePackage, self).install_extension(unpack_src=True)

            # create temporary tarball from unpacked & patched source
            src = os.path.join(tempfile.gettempdir(), '%s-%s-patched.tar.gz' % (self.name, self.version))
            cwd = change_dir(os.path.dirname(self.ext_dir))
            run_shell_cmd("tar cfvz %s %s" % (src, os.path.basename(self.ext_dir)))
            change_dir(cwd)
        else:
            src = self.src

        # need to specify two install locations, to avoid that $HOME/octave is abused;
        # one general package installation prefix, one for architecture-dependent files
        pkg_prefix = os.path.join(self.installdir, 'share', 'octave', 'packages')
        pkg_arch_dep_prefix = pkg_prefix + '-arch-dep'
        octave_cmd = "pkg prefix %s %s; " % (pkg_prefix, pkg_arch_dep_prefix)

        octave_cmd += "pkg install -global %s" % src

        run_shell_cmd("octave --eval '%s'" % octave_cmd)
