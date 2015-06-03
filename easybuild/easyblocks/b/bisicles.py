##
# Copyright 2009-2014 Ghent University
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
EasyBuild support for BISICLES, implemented as an easyblock

@author: Balazs Hajgato (VUB)
"""
import os
import easybuild.tools.toolchain as toolchain

from easybuild.framework.easyblock import EasyBlock
from easybuild.easyblocks.chombo import build_Chombo_BISICLES
from easybuild.tools.modules import get_software_root, get_software_libdir
from easybuild.tools.run import run_cmd


class EB_BISICLES(EasyBlock):
    """Support for building and installing BISICLES."""

    def __init__(self, *args, **kwargs):
        """Initialisation of custom class variables for BISICLES."""
        super(EB_BISICLES, self).__init__(*args, **kwargs)

    def configure_step(self):
        """No configure step for BISICLES."""
        pass 

    def build_step(self):
        """Build BISICLES."""

        build_Chombo_BISICLES(self)

        # Ugly but no better idea:
        for file in os.listdir(self.builddir):
            if file.startswith("Chombo-"):
                chombo_home = os.path.join(self.builddir, file)

        cmd = "cd %s/lib && make setup" % chombo_home
        run_cmd(cmd, log_all=True, simple=False)

        self.cfg.update('buildopts', "CHOMBO_HOME=%s/lib " % chombo_home)
        self.cfg.update('buildopts', "BISICLES_HOME=%s/BISICLES-%s " % (self.builddir, self.version))

        for programbuild in ['exec2D', 'filetools', 'controlproblem']:
            cmd = "cd %s/BISICLES-%s/code/%s && make %s DIM=2 %s all" % (self.builddir, self.version, programbuild, self.paropts, self.cfg['buildopts'])
            run_cmd(cmd, log_all=True, simple=False)

    def test_step(self):
        """No testsuite provided with the source"""
        pass

    def install_step(self):
        """Custom install procedure for BISICLES."""

        cmd = "mkdir %(inst)s/bin && mv code/{exec2D,filetools}/*.ex %(inst)s/bin " % {'inst': self.installdir}
        run_cmd(cmd, log_all=True, simple=True)

        cmd = "mv code/controlproblem/c*.ex %s/bin " % (self.installdir)
        run_cmd(cmd, log_all=True, simple=True)

    def sanity_check_step(self):
        """Custom sanity check for BISICLES."""

        libsuff = "2d.Linux.64.%s.%s.OPT" % (os.getenv('CXX'),os.getenv('F90'))
        if self.toolchain.options.get('usempi', None):
            libsuff += ".MPI"

        if  get_software_root("PETSc"):
            libsuff += ".PETSC"

        if self.toolchain.options['pic']:
            libsuff += ".pic"

        libsuff += ".ex"

        checkexecs = ['driver', 'nctoamr', 'amrtotxt', 'amrtoplot', 'flatten',
                      'extract', 'merge', 'addbox', 'amrtocf', 'stats',
                      'glfaces', 'faces', 'rescale', 'sum', 'control', 
                     ]

        sanity_check_paths = {
            'files': ['bin/%s%s' % (execs, libsuff) for execs in checkexecs],
            'dirs': [],
        }

        super(EB_BISICLES, self).sanity_check_step(custom_paths=sanity_check_paths)
