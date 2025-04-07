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
EasyBuild support for SCOTCH, implemented as an easyblock

@author: Stijn De Weirdt (Ghent University)
@author: Dries Verdegem (Ghent University)
@author: Kenneth Hoste (Ghent University)
@author: Pieter De Baets (Ghent University)
@author: Jens Timmerman (Ghent University)
"""
import os
from easybuild.tools import LooseVersion

import easybuild.tools.toolchain as toolchain
from easybuild.framework.easyblock import EasyBlock
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import apply_regex_substitutions, change_dir, copy_dir, copy_file
from easybuild.tools.filetools import remove_file, write_file
from easybuild.tools.run import run_shell_cmd


class EB_SCOTCH(EasyBlock):
    """Support for building/installing SCOTCH."""

    @staticmethod
    def extra_options(extra_vars=None):
        """Define custom easyconfig parameters specific to Scotch."""
        extra_vars = {
            'threadedmpi': [None, "Use threaded MPI calls.", CUSTOM],
        }
        return EasyBlock.extra_options(extra_vars)

    def configure_step(self):
        """Configure SCOTCH build: locate the template makefile, copy it to a general Makefile.inc and patch it."""

        # pick template makefile
        comp_fam = self.toolchain.comp_family()
        if comp_fam == toolchain.INTELCOMP:  # @UndefinedVariable
            makefilename = 'Makefile.inc.x86-64_pc_linux2.icc'
        elif comp_fam == toolchain.GCC:  # @UndefinedVariable
            makefilename = 'Makefile.inc.x86-64_pc_linux2'
        else:
            raise EasyBuildError("Unknown compiler family used: %s", comp_fam)

        srcdir = os.path.join(self.cfg['start_dir'], 'src')

        # create Makefile.inc
        makefile_inc = os.path.join(srcdir, 'Makefile.inc')
        copy_file(os.path.join(srcdir, 'Make.inc', makefilename), makefile_inc)
        self.log.debug("Successfully copied Makefile.inc to src dir: %s", makefile_inc)

        # the default behaviour of these makefiles is still wrong
        # e.g., compiler settings, and we need -lpthread
        regex_subs = [
            (r"^CCS\s*=.*$", "CCS\t= $(CC)"),
            (r"^CCP\s*=.*$", "CCP\t= $(MPICC)"),
            (r"^CCD\s*=.*$", "CCD\t= $(MPICC)"),
            # append -lpthread to LDFLAGS
            (r"^LDFLAGS\s*=(?P<ldflags>.*$)", r"LDFLAGS\t=\g<ldflags> -lpthread"),
            # prepend -L${EBROOTZLIB}/lib to LDFLAGS
            (r"^LDFLAGS\s*=(?P<ldflags>.*$)", r"LDFLAGS\t=-L${EBROOTZLIB}/lib \g<ldflags>"),
        ]
        apply_regex_substitutions(makefile_inc, regex_subs)

        # change to src dir for building
        change_dir(srcdir)

    def build_step(self):
        """Build by running build_step, but with some special options for SCOTCH depending on the compiler."""

        ccs = os.environ['CC']
        ccp = os.environ['MPICC']
        ccd = os.environ['MPICC']

        cflags = "-fPIC -O3 -DCOMMON_FILE_COMPRESS_GZ -DCOMMON_PTHREAD -DCOMMON_RANDOM_FIXED_SEED -DSCOTCH_RENAME"
        if self.toolchain.comp_family() == toolchain.GCC:  # @UndefinedVariable
            cflags += " -Drestrict=__restrict"
        else:
            cflags += " -restrict -DIDXSIZE64"

        # USE 64 bit index
        if self.toolchain.options['i8']:
            cflags += " -DINTSIZE64"

        if self.cfg['threadedmpi']:
            cflags += " -DSCOTCH_PTHREAD"

        # actually build
        apps = ['scotch', 'ptscotch']
        if LooseVersion(self.version) >= LooseVersion('6.0'):
            # separate target for esmumps in recent versions
            apps.extend(['esmumps', 'ptesmumps'])

        for app in apps:
            cmd = 'make CCS="%s" CCP="%s" CCD="%s" CFLAGS="%s" %s' % (ccs, ccp, ccd, cflags, app)
            run_shell_cmd(cmd)

    def install_step(self):
        """Install by copying files and creating group library file."""

        self.log.debug("Installing SCOTCH by copying files")

        for subdir in ['bin', 'include', 'lib', 'man']:
            copy_dir(os.path.join(self.cfg['start_dir'], subdir), os.path.join(self.installdir, subdir))

        # remove metis.h and parmetis.h include files, since those can only cause trouble
        for header in ['metis.h', 'parmetis.h']:
            remove_file(os.path.join(self.installdir, 'include', header))

        # create group library file
        scotchlibdir = os.path.join(self.installdir, 'lib')
        scotchgrouplib = os.path.join(scotchlibdir, 'libscotch_group.a')

        line = "GROUP (%s)" % ' '.join(os.listdir(scotchlibdir))
        write_file(scotchgrouplib, line)
        self.log.info("Successfully written group lib file: %s", scotchgrouplib)

    def sanity_check_step(self):
        """Custom sanity check for SCOTCH."""

        custom_paths = {
            'files': [],
            'dirs': [],
        }

        binaries = ['acpl', 'amk_ccc', 'amk_fft2', 'amk_grf', 'amk_hy', 'amk_m2', 'amk_p2', 'atst',
                    'dggath', 'dgmap', 'dgord', 'dgpart', 'dgscat', 'dgtst', 'gbase', 'gcv', 'gmap',
                    'gmk_hy', 'gmk_m2', 'gmk_m3', 'gmk_msh', 'gmk_ub2', 'gmtst', 'gord', 'gotst',
                    'gout', 'gpart', 'gscat', 'gtst', 'mcv', 'mmk_m2', 'mmk_m3', 'mord', 'mtst']
        custom_paths['files'].extend([os.path.join('bin', x) for x in binaries])

        headers = ['esmumps', 'ptscotch', 'ptscotchf', 'scotch', 'scotchf']
        custom_paths['files'].extend([os.path.join('include', '%s.h' % x) for x in headers])

        libraries = ['esmumps', 'ptesmumps', 'ptscotch', 'ptscotcherr', 'ptscotcherrexit',
                     'scotch', 'scotch_group', 'scotcherr', 'scotcherrexit']
        custom_paths['files'].extend([os.path.join('lib', 'lib%s.a' % x) for x in libraries])

        custom_commands = []

        # only hard check for recent SCOTCH versions;
        # older versions like '5.1.12b_esmumps' require more effort (not worth it)
        if LooseVersion(self.version) > LooseVersion('6.0.0'):
            # make sure installed SCOTCH version matches what we expect,
            # since it's easy to download the wrong tarball
            # cfr. https://github.com/easybuilders/easybuild-easyconfigs/issues/7154
            # (for '5.1.12b_esmumps', check with 'version 5.1.12')
            custom_commands.append("acpl -V 2>&1 | grep 'version %s'" % self.version.split('_')[0].strip('ab'))

        super(EB_SCOTCH, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)
