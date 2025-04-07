##
# Copyright 2013-2025 Ghent University
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
EasyBuild support for building and installing DualSPHysics, implemented as an easyblock

@author: Jasper Grimm (University of York)
"""
import glob
import os
import stat

from easybuild.easyblocks.generic.cmakemakecp import CMakeMakeCp
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.config import build_option
from easybuild.tools.filetools import adjust_permissions
from easybuild.tools.modules import get_software_root
from easybuild.tools.run import run_shell_cmd


class EB_DualSPHysics(CMakeMakeCp):
    """Support for building/installing DualSPHysics."""

    @staticmethod
    def extra_options():
        """Extra easyconfig parameters for DualSPHysics."""
        extra_vars = CMakeMakeCp.extra_options()

        extra_vars['separate_build_dir'][0] = True

        # files_to_copy is not mandatory here since we set it in the easyblock
        extra_vars['files_to_copy'][2] = CUSTOM
        return extra_vars

    def __init__(self, *args, **kwargs):
        """Initialize calss variables custom to DualSPHysics."""
        super(EB_DualSPHysics, self).__init__(*args, **kwargs)

        self.dsph_target = None
        self.shortver = '.'.join(self.version.split('.')[0:2])

    def prepare_step(self, *args, **kwargs):
        """Determine name of binary that will be installed."""
        super(EB_DualSPHysics, self).prepare_step(*args, **kwargs)

        if get_software_root('CUDA'):
            self.dsph_target = 'GPU'
        else:
            self.dsph_target = 'CPU'

    def configure_step(self):
        """Custom configure procedure for DualSPHysics."""
        srcdir = os.path.join(self.cfg['start_dir'], 'src/source')
        super(EB_DualSPHysics, self).configure_step(srcdir=srcdir)

    def install_step(self):
        """Custom install procedure for DualSPHysics."""
        # *_linux64 binaries are missing execute permissions
        bindir = os.path.join(self.cfg['start_dir'], 'bin', 'linux')
        for b in glob.glob(os.path.join(bindir, '*_linux64')):
            perms = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
            adjust_permissions(b, perms, add=True)

        # no `make install` target
        self.cfg['files_to_copy'] = [
            (['bin/linux/*'], 'bin'),
            (['src/lib/linux_gcc/*'], 'lib'),
        ]
        super(EB_DualSPHysics, self).install_step()

    def post_processing_step(self):
        """Custom post-installation step: ensure rpath is patched into binaries/libraries if configured."""
        super(EB_DualSPHysics, self).post_processing_step()

        if build_option('rpath'):
            # only the compiled binary (e.g. DualSPHysics5.0CPU_linux64) is rpath'd, the precompiled libraries
            # and binaries are not
            # simple solution: copy the RPATH from the compiled binary to the others, then strip excess paths
            rpathed_bin = os.path.join(
                self.installdir, 'bin', 'DualSPHysics%s%s_linux64' % (self.shortver, self.dsph_target)
            )

            res = run_shell_cmd("patchelf --print-rpath %s" % rpathed_bin, hidden=True)
            comp_rpath = res.output.strip()

            files_to_patch = []
            for x in [('bin', '*_linux64'), ('bin', '*.so'), ('lib', '*.so')]:
                files_to_patch.extend(glob.glob(os.path.join(self.installdir, *x)))

            try:
                for x in files_to_patch:
                    res = run_shell_cmd("patchelf --print-rpath %s" % x, hidden=True)
                    self.log.debug("Original RPATH for %s: %s" % (res.output, x))

                    run_shell_cmd("patchelf --set-rpath '%s' --force-rpath %s" % (comp_rpath, x), hidden=True)
                    run_shell_cmd("patchelf --shrink-rpath --force-rpath %s" % x, hidden=True)

                    res = run_shell_cmd("patchelf --print-rpath %s" % x, hidden=True)
                    self.log.debug("RPATH for %s (after patching and shrinking): %s" % (res.output, x))

            except OSError as err:
                raise EasyBuildError("Failed to patch RPATH section in binaries/libraries: %s", err)

    def sanity_check_step(self):
        """Custom sanity checks for DualSPHysics."""

        # repeated here in case other steps are skipped (e.g. due to --sanity-check-only)
        if get_software_root('CUDA'):
            self.dsph_target = 'GPU'
        else:
            self.dsph_target = 'CPU'

        bins = ['GenCase', 'PartVTK', 'IsoSurface', 'MeasureTool', 'GenCase_MkWord', 'DualSPHysics4.0_LiquidGas',
                'DualSPHysics4.0_LiquidGasCPU', 'DualSPHysics%s' % self.shortver,
                'DualSPHysics%s%s' % (self.shortver, self.dsph_target), 'DualSPHysics%s_NNewtonian' % self.shortver,
                'DualSPHysics%s_NNewtonianCPU' % self.shortver]

        custom_paths = {
            'files': ['bin/%s_linux64' % x for x in bins],
            'dirs': ['lib'],
        }

        custom_commands = ['%s_linux64 -h' % x for x in bins]

        super(EB_DualSPHysics, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)
