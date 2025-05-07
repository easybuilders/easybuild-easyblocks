##
# This file is an EasyBuild reciPY as per https://github.com/easybuilders/easybuild
#
# Copyright:: Copyright 2012-2025 Uni.Lu/LCSB, NTUA
# Authors::   Cedric Laczny <cedric.laczny@uni.lu>, Kenneth Hoste
# Authors::   George Tsouloupas <g.tsouloupas@cyi.ac.cy>, Fotis Georgatos <fotis@cern.ch>
# License::   MIT/GPL
# $Id$
#
# This work implements a part of the HPCBIOS project and is a component of the policy:
# http://hpcbios.readthedocs.org/en/latest/HPCBIOS_2012-94.html
##
"""
EasyBuild support for building and installing BWA, implemented as an easyblock

@author: Cedric Laczny (Uni.Lu)
@author: Fotis Georgatos (Uni.Lu)
@author: Kenneth Hoste (Ghent University)
@author: George Tsouloupas <g.tsouloupas@cyi.ac.cy>
"""
import os
import glob
from easybuild.tools import LooseVersion

from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import copy_file, mkdir


class EB_BWA(ConfigureMake):
    """
    Support for building BWA
    """

    def __init__(self, *args, **kwargs):
        """Add extra config options specific to BWA."""
        super(EB_BWA, self).__init__(*args, **kwargs)

        self.files = ['bwa', 'qualfa2fq.pl', 'xa2multi.pl']
        if LooseVersion(self.version) < LooseVersion('0.7.0'):
            # solid2fastq was dropped in recent versions because the same functionality
            # is covered by other tools already
            # cfr. http://osdir.com/ml/general/2010-10/msg26205.html
            self.files.append('solid2fastq.pl')
        self.includes = []
        self.libs = ['libbwa.a']

    def configure_step(self):
        """
        Empty function as BWA comes with _no_ configure script
        """
        pass

    def build_step(self):
        """Custom build procedure: pass down compiler command and options as arguments to 'make'."""

        for env_var in ('CC', 'CFLAGS'):
            if env_var + '=' not in self.cfg['buildopts']:
                self.cfg.update('buildopts', env_var + '="$' + env_var + '"')

        super(EB_BWA, self).build_step()

    def install_step(self):
        """
        Install by copying files to install dir
        """
        srcdir = self.cfg['start_dir']
        # copy binaries
        bindir = os.path.join(self.installdir, 'bin')
        mkdir(bindir)
        for filename in self.files:
            srcfile = os.path.join(srcdir, filename)
            copy_file(srcfile, bindir)

        # copy include files
        includes = glob.glob(os.path.join(srcdir, '*.h'))
        self.includes = [os.path.basename(include) for include in includes]
        incdir = os.path.join(self.installdir, 'include', 'bwa')
        if not self.includes:
            raise EasyBuildError("Unable to find header files")

        mkdir(incdir, parents=True)
        for filename in self.includes:
            srcfile = os.path.join(srcdir, filename)
            copy_file(srcfile, incdir)

        # copy libraries
        libdir = os.path.join(self.installdir, 'lib')
        mkdir(libdir)
        for filename in self.libs:
            srcfile = os.path.join(srcdir, filename)
            copy_file(srcfile, libdir)

        manfile = os.path.join(srcdir, 'bwa.1')
        manman1dir = os.path.join(self.installdir, 'man', 'man1')
        mkdir(manman1dir, parents=True)
        copy_file(manfile, manman1dir)

    def sanity_check_step(self):
        """Custom sanity check for BWA."""

        bins = [os.path.join('bin', x) for x in self.files]
        incs = [os.path.join('include', 'bwa', x) for x in self.includes]
        libs = [os.path.join('lib', 'libbwa.a')]

        custom_paths = {
            'files': bins + incs + libs,
            'dirs': []
        }

        # 'bwa' command doesn't have a --help option, but it does print help-like information to stderr
        # when run without arguments (and exits with exit code 1)
        custom_commands = ["bwa 2>&1 | grep 'index sequences in the FASTA format'"]

        super(EB_BWA, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)
