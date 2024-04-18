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
EasyBuild support for installing Ansys Electronics Desktop

@author: Chia-Jung Hsu (Chalmers University of Technology)
"""
import os
import glob
import tempfile

from easybuild.easyblocks.generic.packedbinary import PackedBinary
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.run import run_cmd


class EB_AEDT(PackedBinary):
    """Support for installing Ansys Electronics Desktop."""

    def __init__(self, *args, **kwargs):
        """Initialize Ansys Electronics Desktop specific variables."""
        super(EB_AEDT, self).__init__(*args, **kwargs)
        self.subdir = None

    def _set_subdir(self):
        idirs = glob.glob(os.path.join(self.installdir, 'v*/Linux*/'))
        if len(idirs) == 1:
            self.subdir = os.path.relpath(idirs[0], self.installdir)
        else:
            raise EasyBuildError("Failed to locate single install subdirectory v*/Linux*/")

    def install_step(self):
        """Install Ansys Electronics Desktop using its setup tool."""
        licserv = os.getenv('EB_AEDT_LICENSE_SERVER')
        licport = os.getenv('EB_AEDT_LICENSE_SERVER_PORT')
        licservs = licserv.split(',')
        licservopt = ["-DLICENSE_SERVER%d=%s" % (i, serv) for i, serv in enumerate(licservs, 1)]
        redundant = len(licservs) > 1
        options = " ".join([
            "-i silent",
            "-DUSER_INSTALL_DIR=%s" % self.installdir,
            "-DTMP_DIR=%s" % tempfile.TemporaryDirectory().name,
            "-DLIBRARY_COMMON_INSTALL=1",
            "-DSPECIFY_LIC_CFG=1",
            "-DREDUNDANT_SERVERS=%d" % redundant,
            *licservopt,
            "-DSPECIFY_PORT=1",
            "-DLICENSE_PORT=%s" % licport,
        ])
        cmd = "./Linux/AnsysEM/Disk1/InstData/setup.exe %s" % options
        run_cmd(cmd, log_all=True, simple=True)

    def post_install_step(self):
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

        txt = super(EB_AEDT, self).make_module_extra()
        version = self.version[2:].replace('R', '')

        idirs = glob.glob(os.path.join(self.installdir, 'v*/Linux*/'))
        if len(idirs) == 1:
            subdir = os.path.relpath(idirs[0], self.installdir)
            # PyAEDT and other tools use the variable to find available AEDT versions
            txt += self.module_generator.set_environment('ANSYSEM_ROOT%s' % version,
                                                         os.path.join(self.installdir, self.subdir))

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

        inpfile = os.path.join(self.subdir, 'Examples', 'RMxprt', 'lssm', 'sm-1.aedt')
        custom_commands = ['ansysedt -ng -BatchSolve -Distributed %s' % inpfile]

        super(EB_AEDT, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)
