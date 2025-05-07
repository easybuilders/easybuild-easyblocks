##
# Copyright 2012-2025 Ghent University
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
EasyBuild support for CUDA compat libraries, implemented as an easyblock

Ref: https://docs.nvidia.com/deploy/cuda-compatibility/index.html#manually-installing-from-runfile

@author: Alexander Grund (TU Dresden)
"""

import os
from easybuild.tools import LooseVersion

from easybuild.easyblocks.generic.binary import Binary
from easybuild.framework.easyconfig import CUSTOM, MANDATORY
from easybuild.tools.build_log import EasyBuildError, print_warning
from easybuild.tools.config import build_option, IGNORE
from easybuild.tools.filetools import copy_file, find_glob_pattern, mkdir, symlink, which
from easybuild.tools.run import run_shell_cmd


class EB_CUDAcompat(Binary):
    """
    Support for installing CUDA compat libraries.
    """

    @staticmethod
    def extra_options():
        """Add variable for driver version"""
        extra_vars = Binary.extra_options()
        extra_vars.update({
            'compatible_driver_versions': [None, "Minimum (system) CUDA driver versions which are compatible", CUSTOM],
            'nv_version': [None, "Version of the driver package", MANDATORY],
        })
        # We don't need the extract and install step from the Binary EasyBlock
        del extra_vars['extract_sources']
        del extra_vars['install_cmd']
        # And also no need to modify the PATH
        del extra_vars['prepend_to_path']
        return extra_vars

    def __init__(self, *args, **kwargs):
        """Initialize custom class variables for CUDACompat."""
        super(EB_CUDAcompat, self).__init__(*args, **kwargs)
        self._has_nvidia_smi = None
        # avoid building software with this compat libraries
        self.module_load_environment.remove('LIBRARY_PATH')

    @property
    def has_nvidia_smi(self):
        """Return whether the system has nvidia-smi and print a warning once if not"""
        if self._has_nvidia_smi is None:
            self._has_nvidia_smi = which('nvidia-smi', on_error=IGNORE) is not None
            if not self._has_nvidia_smi:
                print_warning('Could not find nvidia-smi. Assuming a system without GPUs and skipping checks!')
        return self._has_nvidia_smi

    def _run_nvidia_smi(self, args):
        """
        Run nvidia-smi with the given argument(s) and return the output.

        Also does sensible logging.
        Raises RuntimeError on failure.
        """
        if not self.has_nvidia_smi:
            raise RuntimeError('Could not find nvidia-smi.')
        cmd = 'nvidia-smi ' + args
        res = run_shell_cmd(cmd, fail_on_error=False)
        if res.exit_code != 0:
            raise RuntimeError("`%s` returned exit code %s with output:\n%s" % (cmd, res.exit_code, res.output))
        else:
            self.log.info('`%s` succeeded with output:\n%s' % (cmd, res.output))
            return res.output.strip().split('\n')

    def prepare_step(self, *args, **kwargs):
        """Parse and check the compatible_driver_versions value of the EasyConfig"""
        compatible_driver_versions = self.cfg.get('compatible_driver_versions')
        if compatible_driver_versions:
            try:
                # Create a dictionary with the major version as the keys
                self.compatible_driver_version_map = {
                    int(v.split('.', 1)[0]): v
                    for v in compatible_driver_versions
                }
            except ValueError:
                raise EasyBuildError("Invalid format of compatible_driver_versions. "
                                     "Expected numeric major versions, got '%s'", compatible_driver_versions)
        else:
            self.compatible_driver_version_map = None
        if 'LD_LIBRARY_PATH' in (build_option('filter_env_vars') or []):
            raise EasyBuildError("This module relies on setting $LD_LIBRARY_PATH, "
                                 "so you need to remove this variable from --filter-env-vars")
        super(EB_CUDAcompat, self).prepare_step(*args, **kwargs)

    def fetch_step(self, *args, **kwargs):
        """Check for EULA acceptance prior to getting sources."""
        # EULA for NVIDIA driver must be accepted via --accept-eula-for EasyBuild configuration option,
        # or via 'accept_eula = True' in easyconfig file
        self.check_accepted_eula(
            name='NVIDIA-driver',
            more_info='https://www.nvidia.com/content/DriverDownload-March2009/licence.php?lang=us'
        )
        return super(EB_CUDAcompat, self).fetch_step(*args, **kwargs)

    def extract_step(self):
        """Extract the files without running the installer."""
        execpath = self.src[0]['path']
        tmpdir = os.path.join(self.builddir, 'tmp')
        targetdir = os.path.join(self.builddir, 'extracted')
        run_shell_cmd("/bin/sh " + execpath + " --extract-only --tmpdir='%s' --target '%s'" % (tmpdir, targetdir))
        self.src[0]['finalpath'] = targetdir

    def test_step(self):
        """
        Check for a compatible driver version if the EC has that information.

        This can be skipped with `--skip-test-step`.
        """

        if self.compatible_driver_version_map and self.has_nvidia_smi:
            try:
                out_lines = self._run_nvidia_smi('--query-gpu=driver_version --format=csv,noheader')
                if not out_lines or not out_lines[0]:
                    raise RuntimeError('nvidia-smi did not find any GPUs on the system')
                driver_version = out_lines[0]
                version_parts = driver_version.split('.')
                if len(version_parts) < 3 or any(not v.isdigit() for v in version_parts):
                    raise RuntimeError("Expected the version to be in format x.y.z (all numeric) "
                                       "but got '%s'" % driver_version)
            except RuntimeError as err:
                self.log.warning("Failed to get the CUDA driver version: %s", err)
                driver_version = None

            if not driver_version:
                print_warning('Failed to determine the CUDA driver version, so skipping the compatibility check!')
            else:
                driver_version_major = int(driver_version.split('.', 1)[0])
                compatible_driver_versions = ', '.join(sorted(self.compatible_driver_version_map.values()))
                try:
                    min_required_version = self.compatible_driver_version_map[driver_version_major]
                except KeyError:
                    raise EasyBuildError('The installed CUDA driver %s is not a supported branch/major version for '
                                         '%s %s. Supported drivers: %s',
                                         driver_version, self.name, self.version, compatible_driver_versions)
                if LooseVersion(driver_version) < min_required_version:
                    raise EasyBuildError('The installed CUDA driver %s is to old for %s %s, '
                                         'need at least %s. Supported drivers: %s',
                                         driver_version, self.name, self.version,
                                         min_required_version, compatible_driver_versions)
                else:
                    self.log.info('The installed CUDA driver %s appears to be supported.', driver_version)

        return super(EB_CUDAcompat, self).test_step()

    def install_step(self):
        """Install CUDA compat libraries by copying library files and creating the symlinks."""
        libdir = os.path.join(self.installdir, 'lib')
        mkdir(libdir)

        # From https://docs.nvidia.com/deploy/cuda-compatibility/index.html#installing-from-network-repo:
        # The cuda-compat package consists of the following files:
        #   - libcuda.so.* - the CUDA Driver
        #   - libnvidia-nvvm.so.* - JIT LTO ( CUDA 11.5 and later only)
        #   - libnvidia-ptxjitcompiler.so.* - the JIT (just-in-time) compiler for PTX files

        library_globs = [
            'libcuda.so.*',
            'libnvidia-ptxjitcompiler.so.*',
        ]
        if LooseVersion(self.version) >= '11.5':
            library_globs.append('libnvidia-nvvm.so.*')

        startdir = self.cfg['start_dir']
        nv_version = self.cfg['nv_version']
        for library_glob in library_globs:
            library_path = find_glob_pattern(os.path.join(startdir, library_glob))
            library = os.path.basename(library_path)
            # Sanity check the version
            if library_glob == 'libcuda.so.*':
                library_version = library.split('.', 2)[2]
                if library_version != nv_version:
                    raise EasyBuildError('Expected driver version %s (from nv_version) but found %s '
                                         '(determined from file %s)', nv_version, library_version, library_path)

            copy_file(library_path, os.path.join(libdir, library))
            if library.endswith('.' + nv_version):
                # E.g. libcuda.so.510.73.08 -> libcuda.so.1
                versioned_symlink = library[:-len(nv_version)] + '1'
            else:
                # E.g. libnvidia-nvvm.so.4.0.0 -> libnvidia-nvvm.so.4
                versioned_symlink = library.rsplit('.', 2)[0]
            symlink(library, os.path.join(libdir, versioned_symlink), use_abspath_source=False)
            # E.g. libcuda.so.1 -> libcuda.so
            unversioned_symlink = versioned_symlink.rsplit('.', 1)[0]
            symlink(versioned_symlink, os.path.join(libdir, unversioned_symlink), use_abspath_source=False)

    def sanity_check_step(self):
        """Check for core files (unversioned libs, symlinks)"""
        libraries = [
            'libcuda.so',
            'libnvidia-ptxjitcompiler.so',
        ]
        if LooseVersion(self.version) >= '11.5':
            libraries.append('libnvidia-nvvm.so')
        custom_paths = {
            'files': [os.path.join(self.installdir, 'lib', x) for x in libraries],
            'dirs': ['lib', 'lib64'],
        }
        super(EB_CUDAcompat, self).sanity_check_step(custom_paths=custom_paths)

        if self.has_nvidia_smi:
            fake_mod_data = None

            # skip loading of fake module when using --sanity-check-only, load real module instead
            if build_option('sanity_check_only'):
                self.load_module()
            elif not self.dry_run:
                fake_mod_data = self.load_fake_module(purge=True, verbose=True)

            try:
                out_lines = self._run_nvidia_smi('--query --display=COMPUTE')

                if fake_mod_data:
                    self.clean_up_fake_module(fake_mod_data)

                cuda_version = next((line.rsplit(' ', 1)[1] for line in out_lines if line.startswith('CUDA')), None)
                if not cuda_version:
                    raise RuntimeError('Failed to find CUDA version!')
                self.log.info('CUDA version (as per nvidia-smi) after loading the module: ' + cuda_version)
                if LooseVersion(cuda_version) != self.version:
                    raise RuntimeError('Reported CUDA version %s is not %s' % (cuda_version, self.version))
            except RuntimeError as err:
                if fake_mod_data:
                    self.clean_up_fake_module(fake_mod_data)
                raise EasyBuildError('Version check via nvidia-smi after loading the module failed: %s', err)
