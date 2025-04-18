# This file is an EasyBuild reciPY as per https://github.com/easybuilders/easybuild
# Author: Pablo Escobar Lopez
# Swiss Institute of Bioinformatics
# Biozentrum - University of Basel
"""
EasyBuild support for installing Chimera, implemented as an easyblock
"""

import os

from easybuild.easyblocks.generic.packedbinary import PackedBinary
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import mkdir, symlink
from easybuild.tools.run import run_shell_cmd


class EB_Chimera(PackedBinary):
    """Support for installing Chimera."""

    def extract_step(self, verbose=False):
        """Custom extraction of sources for Chimera: unpack installation file
        to obtain chimera.bin installer."""

        cmd = "unzip -d %s %s" % (self.builddir, self.src[0]['path'])
        run_shell_cmd(cmd)

    def install_step(self):
        """Install using chimera.bin."""

        try:
            os.chdir(self.cfg['start_dir'])
        except OSError as err:
            raise EasyBuildError("Failed to change to %s: %s", self.cfg['start_dir'], err)

        # Chimera comes bundled with its dependencies, and follows a
        # UNIX file system layout with 'bin', 'include', 'lib', etc.  To
        # avoid conflicts with other modules, the Chimera module must
        # not add the 'bin', 'include', 'lib', etc. directories to PATH,
        # CPATH, LD_LIBRARY_PATH, etc.  We achieve this by installing
        # Chimera in a subdirectory (called 'chimera') instead of the
        # root directory.
        cmd = "./chimera.bin -q -d %s" % os.path.join(self.installdir,
                                                      'chimera')
        run_shell_cmd(cmd)

        # Create a symlink to the Chimera startup script; this symlink
        # will end up in PATH.  The startup script sets up the
        # environment, so that Chimera finds its dependencies.
        mkdir(os.path.join(self.installdir, 'bin'))
        symlink(os.path.join(self.installdir, 'chimera', 'bin', 'chimera'),
                os.path.join(self.installdir, 'bin', 'chimera'))
