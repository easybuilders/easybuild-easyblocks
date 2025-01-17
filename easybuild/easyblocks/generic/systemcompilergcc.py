##
# Copyright 2015-2024 Ghent University
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
EasyBuild support for using (already installed/existing) system compiler based
on GCC instead of a full install via EasyBuild.

@author Bernd Mohr (Juelich Supercomputing Centre)
@author Kenneth Hoste (Ghent University)
@author Alan O'Cais (Juelich Supercomputing Centre)
@author Alex Domingo (Vrije Universiteit Brussel)
"""
from easybuild.easyblocks.gcc import EB_GCC
from easybuild.easyblocks.generic.systemcompiler import SystemCompiler


# order matters, SystemCompiler goes first to avoid recursion whenever EB_GCC calls super()
class SystemCompilerGCC(SystemCompiler, EB_GCC):
    """
    Support for generating a module file for a system compiler based on GCC with specified name.

    The compiler is expected to be available in $PATH, required libraries are assumed to be readily available.

    Specifying 'system' as a version leads to using the derived compiler version in the generated module;
    if an actual version is specified, it is checked against the derived version of the system compiler that was found.
    """
    @staticmethod
    def extra_options():
        """Add custom easyconfig parameters for SystemCompilerGCC easyblock."""
        extra_vars = EB_GCC.extra_options()
        extra_vars.update(SystemCompiler.extra_options())
        return extra_vars

    def __init__(self, *args, **kwargs):
        """Extra initialization: keep track of values that may change due to modifications to the version."""
        super().__init__(*args, **kwargs)

        # use GCC compiler class to generate standalone module
        if self.cfg['generate_standalone_module']:
            self.compiler_class = EB_GCC
