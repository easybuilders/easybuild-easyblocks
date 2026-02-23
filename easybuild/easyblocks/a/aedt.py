##
# Copyright 2009-2026 Ghent University
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
EasyBuild support for installing Ansys Electronics Desktop

@author: Chia-Jung Hsu (Chalmers University of Technology)
"""
import os
import glob
import shutil
import tempfile

from easybuild.easyblocks.generic.packedbinary import PackedBinary
from easybuild.tools import LooseVersion
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.run import run_shell_cmd


class EB_AEDT(PackedBinary):
    """Support for installing Ansys Electronics Desktop."""

    def __init__(self, *args, **kwargs):
        """Initialize Ansys Electronics Desktop specific variables."""
        super().__init__(*args, **kwargs)
        self.subdir = None

    def _set_subdir(self):

        ver = LooseVersion(self.version)
        if ver > LooseVersion("2024R1"):
            pattern = 'v*/AnsysEM/'
        else:
            pattern = 'v*/Linux*/'
        idirs = glob.glob(os.path.join(self.installdir, pattern))

        if len(idirs) == 1:
            self.subdir = os.path.relpath(idirs[0], self.installdir)
        else:
            raise EasyBuildError(f"Failed to locate single install subdirectory {pattern}")

    def install_step(self):
        """Install Ansys Electronics Desktop using its setup tool."""

        ver = LooseVersion(self.version)
        licserv = os.getenv('EB_AEDT_LICENSE_SERVER')
        licport = os.getenv('EB_AEDT_LICENSE_SERVER_PORT')
        licservs = licserv.split(',')
        licservopt = ["-DLICENSE_SERVER%d=%s" % (i, serv) for i, serv in enumerate(licservs, 1)]
        redundant = len(licservs) > 1

        tempdir = tempfile.TemporaryDirectory()
        if ver > LooseVersion("2024R1"):
            installer = "./INSTALL"
            cmd = " ".join([
                installer,
                "-silent",
                "-install_dir %s" % self.installdir,
                "-licserverinfo :%s:%s" % (licport, licserv),
                "-usetempdir %s" % tempdir.name,
            ])
        else:
            installer = "./Linux/AnsysEM/Disk1/InstData/setup.exe"

            cmd = " ".join([
                installer,
                "-i silent",
                "-DUSER_INSTALL_DIR=%s" % self.installdir,
                "-DTMP_DIR=%s" % tempdir.name,
                "-DLIBRARY_COMMON_INSTALL=1",
                "-DSPECIFY_LIC_CFG=1",
                "-DREDUNDANT_SERVERS=%d" % redundant,
                *licservopt,
                "-DSPECIFY_PORT=1",
                "-DLICENSE_PORT=%s" % licport,
            ])
        run_shell_cmd(cmd)

    def post_processing_step(self):
        """Disable OS check and set LC_ALL/LANG for runtime"""
        if not self.subdir:
            self._set_subdir()

        # Clean script file to disable over restrict OS checking
        with open(os.path.join(self.installdir, self.subdir, "VerifyOS.bash"), "w") as f:
            f.write("")

        # Follow the settings in .setup_runtime and .setup_runtime_mpi to set LC_ALL and LANG
        # If LC_ALL is not set properly, AEDT throws the following runtime error:
        # what():  locale::facet::_S_create_c_locale name not valid
        for fname in [".setup_runtime", ".setup_runtime_mpi"]:
            with open(os.path.join(self.installdir, self.subdir, fname), "r") as f:
                orig = f.read()
            with open(os.path.join(self.installdir, self.subdir, fname), "w") as f:
                f.write("export LC_ALL=C\n")
                f.write("export LANG=C\n")
                f.write(orig)

    def make_module_extra(self):
        """Extra module entries for Ansys Electronics Desktop."""

        txt = super().make_module_extra()
        ver = LooseVersion(self.version)
        short_ver = self.version[2:].replace('R', '')

        if ver > LooseVersion("2024R1"):
            pattern = 'v*/AnsysEM/'
        else:
            pattern = 'v*/Linux*/'
        idirs = glob.glob(os.path.join(self.installdir, pattern))

        if len(idirs) == 1:
            subdir = os.path.relpath(idirs[0], self.installdir)
            # PyAEDT and other tools use the variable to find available AEDT versions
            txt += self.module_generator.set_environment('ANSYSEM_ROOT%s' % short_ver,
                                                         os.path.join(self.installdir, subdir))

            txt += self.module_generator.prepend_paths('PATH', subdir)
            txt += self.module_generator.prepend_paths('LD_LIBRARY_PATH', subdir)
            txt += self.module_generator.prepend_paths('LIBRARY_PATH', subdir)

        return txt

    def sanity_check_step(self):
        """Custom sanity check for Ansys Electronics Desktop."""
        if not self.subdir:
            self._set_subdir()

        custom_paths = {
            'files': [os.path.join(self.subdir, 'ansysedt')],
            'dirs': [self.subdir],
        }

        # Since 2025R1, test examples cannot be directly found in builddir
        # Copy a test example from installdir to a tempdir to prevent writing additional file into installdir
        inpfilesrc = os.path.join(self.installdir, self.subdir, 'Examples', 'RMxprt', 'lssm', 'sm-1.aedt')
        with tempfile.TemporaryDirectory() as tempdir:
            shutil.copy(inpfilesrc, tempdir)
            inpfile = os.path.join(tempdir, 'sm-1.aedt')
            custom_commands = ['ansysedt -ng -batchsolve -Distributed -monitor %s' % inpfile]

        super().sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)
