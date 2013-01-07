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
EasyBuild support for building and installing Trinity, implemented as an easyblock

@authors: Stijn De Weirdt, Dries Verdegem, Pieter De Baets, Kenneth Hoste (UGent)
"""
import fileinput
import os
import re
import shutil
import sys
from distutils.version import LooseVersion

import easybuild.tools.toolchain as toolchain
from easybuild.framework.easyblock import EasyBlock
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.filetools import run_cmd


class EB_Trinity(EasyBlock):
    """Support for building/installing Trinity."""

    def __init__(self, *args, **kwargs):
        """Initialisation of custom class variables for Trinity."""
        EasyBlock.__init__(self, *args, **kwargs)

        self.build_in_installdir = True

    @staticmethod
    def extra_options():
        """Custom easyconfig parameters for Trinity."""

        extra_vars = [
                      ('withsampledata', [False, "Include sample data", CUSTOM]),
                      ('bwapluginver', [None, "BWA pugin version", CUSTOM]),
                      ('RSEMmod', [False, "Enable RSEMmod", CUSTOM]),
                     ]

        return EasyBlock.extra_options(extra_vars)

    def butterfly(self):
        """Install procedure for Butterfly."""

        self.log.info("Begin Butterfly")

        dst = os.path.join(self.cfg['start_dir'], 'Butterfly', 'src')
        try:
            os.chdir(dst)
        except OSError, err:
            self.log.error("Butterfly: failed to change to dst dir %s" % (dst, err))

        cmd = "ant"
        run_cmd(cmd)

        self.log.info("End Butterfly")

    def chrysalis(self, run=True):
        """Install procedure for Chrysalis."""

        make_flags = "COMPILER='%s' CPLUSPLUS='%s' CC='%s' " % (os.getenv('CXX'),
                                                                os.getenv('CXX'),
                                                                os.getenv('CC'))
        make_flags += "OMP_FLAGS='%s' OMP_LINK='%s' " % (self.toolchain.get_flag('openmp'),
                                                         os.getenv('LIBS'))
        make_flags += "OPTIM='-O1' SYS_OPT='-O2 %s' " % self.toolchain.get_flag('optarch')
        make_flags += "OPEN_MP=yes UNSUPPORTED=yes DEBUG=no QUIET=yes"

        if run:
            self.log.info("Begin Chrysalis")

            dst = os.path.join(self.cfg['start_dir'], 'Chrysalis')
            try:
                os.chdir(dst)
            except OSError, err:
                self.log.error("Chrysalis: failed to change to dst dir %s: %s" % (dst, err))

            run_cmd("make clean")
            run_cmd("make %s" % make_flags)

            self.log.info("End Chrysalis")

        else:
            return make_flags

    def inchworm(self, run=True):
        """Install procedure for Inchworm."""

        make_flags = 'CXXFLAGS="%s %s"' % (os.getenv('CXXFLAGS'), self.toolchain.get_flag('openmp'))

        if run:
            self.log.info("Begin Inchworm")

            dst = os.path.join(self.cfg['start_dir'], 'Inchworm')
            try:
                os.chdir(dst)
            except OSError, err:
                self.log.error("Inchworm: failed to change to dst dir %s: %s" % (dst, err))

            run_cmd('./configure --prefix=%s' % dst)
            run_cmd("make install %s" % make_flags)

            self.log.info("End Inchworm")

        else:
            return make_flags

    def kmer(self):
        """Install procedure for kmer (Meryl)."""

        self.log.info("Begin Meryl")

        dst = os.path.join(self.cfg['start_dir'], 'trinity-plugins', 'kmer')
        try:
            os.chdir(dst)
        except OSError, err:
            self.log.error("Meryl: failed to change to dst dir %s: %s" % (dst, err))

        cmd = "./configure.sh"
        run_cmd(cmd)

        cmd = 'make -j 1 CCDEP="%s -MM -MG" CXXDEP="%s -MM -MG"' % (os.getenv('CC'),
                                                                     os.getenv('CXX'))
        run_cmd(cmd)

        cmd = 'make install'
        run_cmd(cmd)

        self.log.info("End Meryl")

    def trinityplugin(self, plugindir, cc=None):
        """Install procedure for Trinity plugins."""

        self.log.info("Begin %s plugin" % plugindir)

        dst = os.path.join(self.cfg['start_dir'], 'trinity-plugins', plugindir)
        try:
            os.chdir(dst)
        except OSError, err:
            self.log.error("%s plugin: failed to change to dst dir %s: %s" % (plugindir, dst, err))

        if not cc:
            cc = os.getenv('CC')

        cmd = "make CC='%s' CXX='%s' CFLAGS='%s'" % (cc, os.getenv('CXX'), os.getenv('CFLAGS'))
        run_cmd(cmd)

        self.log.info("End %s plugin" % plugindir)

    def configure_step(self):
        """No configuration for Trinity."""

        pass

    def build_step(self):
        """No building for Trinity."""

        pass

    def install_step(self):
        """Custom install procedure for Trinity."""

        if LooseVersion(self.version) < LooseVersion('2012-10-05'):
            self.inchworm()
            self.chrysalis()
            self.kmer()
            self.butterfly()

            bwapluginver = self.cfg['bwapluginver']
            if bwapluginver:
                self.trinityplugin('bwa-%s-patched_multi_map' % bwapluginver)

            if self.cfg['RSEMmod']:
                self.trinityplugin('RSEM-mod', cc=os.getenv('CXX'))

        else:

            inchworm_flags = self.inchworm(run=False)
            chrysalis_flags = self.chrysalis(run=False)

            fn = "Makefile"
            for line in fileinput.input(fn, inplace=1, backup='.orig.eb'):

                line = re.sub(r'^(INCHWORM_CONFIGURE_FLAGS\s*=\s*).*$', r'\1%s' % inchworm_flags, line)
                line = re.sub(r'^(CHRYSALIS_MAKE_FLAGS\s*=\s*).*$', r'\1%s' % chrysalis_flags, line)

                sys.stdout.write(line)

            trinity_compiler = None
            comp_fam = self.toolchain.comp_family()
            if comp_fam in [toolchain.INTELCOMP]:
                trinity_compiler = "intel"
            elif comp_fam in [toolchain.GCC]:
                trinity_compiler = "gcc"
            else:
                self.log.error("Don't know how to set TRINITY_COMPILER for %s compiler" % comp_fam)

            cmd = "make TRINITY_COMPILER=%s" % trinity_compiler
            run_cmd(cmd)

            # butterfly is not included in standard build
            self.butterfly()

        # remove sample data if desired
        if not self.cfg['withsampledata']:
            try:
                shutil.rmtree(os.path.join(self.cfg['start_dir'], 'sample_data'))
            except OSError, err:
                self.log.error("Failed to remove sample data: %s" % err)

    def sanity_check_step(self):
        """Custom sanity check for Trinity."""

        path = 'trinityrnaseq_r%s' % self.version

        # these lists are definitely non-exhaustive, but better than nothing
        custom_paths = {
                        'files': [os.path.join(path, x) for x in ['Inchworm/bin/inchworm', 'Chrysalis/Chrysalis']],
                        'dirs': [os.path.join(path, x) for x in ['Butterfly/src/bin', 'util']]
                       }

        super(EB_Trinity, self).sanity_check_step(custom_paths=custom_paths)

    def make_module_req_guess(self):
        """Custom tweaks for PATH variable for Trinity."""

        guesses = super(EB_Trinity, self).make_module_req_guess()

        guesses.update({
                        'PATH': [os.path.basename(self.cfg['start_dir'].strip('/'))],
                       })

        return guesses
