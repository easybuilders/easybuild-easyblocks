##
# Copyright 2015 Fokko Masselink
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
EasyBuild support for building and installing Subversion, implemented as an easyblock

@author: Fokko Masselink
"""
import os
import re
import sys
import fileinput
from easybuild.framework.easyblock import EasyBlock
from easybuild.tools.run import run_cmd
from easybuild.tools.filetools import mkdir 
import easybuild.tools.environment as env
import easybuild.tools.toolchain as toolchain


from easybuild.easyblocks.generic.configuremake import ConfigureMake
class EB_SUBVERSION(ConfigureMake):
    """Support for building/installing Subversion."""

    def build_step(self):
        # first build subversion
        super(EB_SUBVERSION, self).build_step()

        # now build Perl bindings
        cmd = "make -j swig-pl-lib"
        run_cmd(cmd, log_all=True, simple=True)

        # now build Python bindings
        cmd = "make -j swig-py"
        run_cmd(cmd, log_all=True, simple=True)


    def install_step(self):
        # install subversion
        super(EB_SUBVERSION, self).install_step()
        
        # install Perl bindings
        cmd = "make install-swig-pl-lib"
        run_cmd(cmd, log_all=True, simple=True)

        cmd = "cd subversion/bindings/swig/perl/native; perl Makefile.PL PREFIX=%s; make install" % self.installdir
        run_cmd(cmd, log_all=True, simple=True)

        # install Python bindings
        cmd = "make install-swig-py DESTDIR=%s" % self.installdir
        run_cmd(cmd, log_all=True, simple=True)

    def make_module_extra(self):
        txt = super(EB_SUBVERSION, self).make_module_extra()
        txt += self.module_generator.prepend_paths("PERL5LIB", ['lib64/perl5'])
        return txt

