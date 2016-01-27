##
# Copyright 2009-2015 Ghent University
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
EasyBuild support for LAMMPS, impelemented as an easyblock.

@author: Benjamin Roberts (Landcare Research NZ Ltd)
"""

from easybuild.framework.easyblock import EasyBlock
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.filetools import apply_regex_substitutions
from easybuild.tools.run import run_cmd

class EB_LAMMPS(EasyBlock):
    """
    Support for building and installing LAMMPS
    """

    @staticmethod
    def extra_options(extra_vars=None):
        """Extra easyconfig parameters specific to ConfigureMake."""
        extra_vars = EasyBlock.extra_options(extra=extra_vars)
        extra_vars.update({
            'use_meam': [False, "Include the optional \"meam\" package", CUSTOM],
        })
        return extra_vars

    def configure_step(self, cmd_prefix=''):
        """
        No separate configure step is necessary
        """
        pass

    def build_step(self, verbose=False, path=None):
        """
        Start the actual build
        - typical: make -j X
        """

        out = None

        src_dir = self.cfg['start_dir']

        # Build meam if requested
        if self.cfg['use_meam']:
            meam_dir = os.path.join(src_dir, 'lib', 'meam')
            os.chdir(meam_dir)
            if self.toolchain.comp_family() in [toolchain.GCC]:
                meam_suffix = 'gfortran'
            elif self.toolchain.comp_family() in [toolchain.INTELCOMP]:
                meam_suffix = 'ifort'
            else:
                raise EasyBuildError("Don't know how to compile meam with compiler {0}".format(self.toolchain.comp_family()))

            cmd = "{0} make -f Makefile.{1} {2}".format(self.cfg['prebuildopts'], meam_suffix, self.cfg['buildopts'])
            (meam_output, _) = run_cmd(cmd, path=path, log_all=True, simple=False, log_output=verbose)

            # Tweak the resulting Makefile.lammps
            if self.toolchain.comp_family() in [toolchain.INTELCOMP]:
                apply_regex_substitutions('Makefile.lammps', [
                    ('^(meam_SYSLIB\s*=.*)\s+lompstub\s+(.*)$', '\1 \2'),
                    ('^(meam_SYSPATH\s*=\s*-L).*$', '\1%s' % os.environ['EBROOTIFORT'])
                ])

            # Go back to the main directory
            os.chdir(src_dir)

            out += meam_output

        # See https://github.com/UoA-eResearch/easierbuild/blob/master/LAMMPS/build_lammps.txt
        # for further instructions, etc.
        return out

    def test_step(self):
        """
        Test the compilation
        - default: None
        """

        if self.cfg['runtest']:
            cmd = "make %s" % (self.cfg['runtest'])
            (out, _) = run_cmd(cmd, log_all=True, simple=False)

            return out

    def install_step(self):
        """
        Create the installation in correct location
        - typical: make install
        """

        cmd = "%s make install %s" % (self.cfg['preinstallopts'], self.cfg['installopts'])

        (out, _) = run_cmd(cmd, log_all=True, simple=False)

        return out
