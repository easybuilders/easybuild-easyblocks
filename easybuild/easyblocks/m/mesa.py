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
EasyBuild support for installing Mesa, implemented as an easyblock

@author: Andrew Edmondson (University of Birmingham)
@author: Kenneth Hoste (HPC-UGent)
@author: Alex Domingo (Vrije Universiteit Brussel)
@author: Alexander Grund (TU Dresden)
"""
import os
from easybuild.tools import LooseVersion

from easybuild.easyblocks.generic.mesonninja import MesonNinja
from easybuild.tools.filetools import copy_dir
from easybuild.tools.systemtools import POWER, X86_64, AARCH64, RISCV64
from easybuild.tools.systemtools import get_cpu_architecture, get_cpu_features, get_shared_lib_ext


class EB_Mesa(MesonNinja):
    """Custom easyblock for building and installing Mesa."""

    def __init__(self, *args, **kwargs):
        """Constructor for custom Mesa easyblock: figure out which values to pass to swr-arches configuration option."""

        super(EB_Mesa, self).__init__(*args, **kwargs)

        self.gallium_configopts = []

        # Mesa fails to build with libunwind on aarch64
        # See https://github.com/easybuilders/easybuild-easyblocks/issues/2150
        if get_cpu_architecture() == AARCH64:
            given_config_opts = self.cfg.get('configopts')
            if "-Dlibunwind=true" in given_config_opts:
                self.log.warning('libunwind not supported on aarch64, stripping from configopts!')
                configopts_libunwind_stripped = given_config_opts.replace('-Dlibunwind=true', '-Dlibunwind=false')
                self.cfg.set_keys({'configopts': configopts_libunwind_stripped})
                self.log.warning('New configopts after stripping: ' + self.cfg.get('configopts'))

        # Check user-defined Gallium drivers
        gallium_drivers = self.get_configopt_value('gallium-drivers')

        if not gallium_drivers:
            # Add appropriate Gallium drivers for current architecture
            arch = get_cpu_architecture()
            arch_gallium_drivers = {
                X86_64: ['swrast'],
                POWER: ['swrast'],
                AARCH64: ['swrast'],
                RISCV64: ['swrast'],
            }
            if LooseVersion(self.version) < LooseVersion('22'):
                # swr driver support removed in Mesa 22.0
                arch_gallium_drivers[X86_64].append('swr')

            if arch in arch_gallium_drivers:
                gallium_drivers = arch_gallium_drivers[arch]
                # Add configopt for additional Gallium drivers
                self.gallium_configopts.append('-Dgallium-drivers=' + ','.join(gallium_drivers))

        self.log.debug('Gallium driver(s) included in the installation: %s' % ', '.join(gallium_drivers))

        self.swr_arches = []

        if 'swr' in gallium_drivers:
            # Check user-defined SWR arches
            self.swr_arches = self.get_configopt_value('swr-arches')

            if not self.swr_arches:
                # Set cpu features of SWR for current micro-architecture
                feat_to_swrarch = {
                    'avx': 'avx',
                    'avx1.0': 'avx',  # on macOS, AVX is indicated with 'avx1.0' rather than 'avx'
                    'avx2': 'avx2',
                    'avx512f': 'skx',  # AVX-512 Foundation - introduced in Skylake
                    'avx512er': 'knl',  # AVX-512 Exponential and Reciprocal Instructions implemented in Knights Landing
                }
                # Determine list of values to pass to swr-arches configuration option
                cpu_features = get_cpu_features()
                self.swr_arches = sorted([swrarch for feat, swrarch in feat_to_swrarch.items() if feat in cpu_features])
                # Add configopt for additional SWR arches
                self.gallium_configopts.append('-Dswr-arches=' + ','.join(self.swr_arches))

            self.log.debug('SWR Gallium driver will support: %s' % ', '.join(self.swr_arches))

    def get_configopt_value(self, configopt_name):
        """
        Return list of values for the given configuration option in configopts
        """
        configopt_args = [opt for opt in self.cfg['configopts'].split() if opt.startswith('-D%s=' % configopt_name)]

        if configopt_args:
            if len(configopt_args) > 1:
                self.log.warning("Found multiple instances of %s in configopts, using last one: %s",
                                 configopt_name, configopt_args[-1])
            # Get value of last option added
            configopt_value = configopt_args[-1].split('=')[-1]
            # Remove quotes and extract individual values
            configopt_value = configopt_value.strip('"\'').split(',')
        else:
            configopt_value = None

        return configopt_value

    def configure_step(self):
        """
        Customise the configure options based on the processor architecture of the host
        (Gallium drivers installed, SWR CPU features, ...)
        """

        if self.gallium_configopts:
            self.cfg.update('configopts', self.gallium_configopts)

        return super(EB_Mesa, self).configure_step()

    def install_step(self):
        """Also copy additional header files after installing Mesa."""

        super(EB_Mesa, self).install_step()

        # also install header files located in include/GL/internal, unless they're available already;
        # we can't enable both DRI and Gallium drivers,
        # but we can provide the DRI header file (GL/internal/dri_interface.h)
        target_inc_GL_internal = os.path.join(self.installdir, 'include', 'GL', 'internal')
        if not os.path.exists(target_inc_GL_internal):
            src_inc_GL_internal = os.path.join(self.start_dir, 'include', 'GL', 'internal')
            copy_dir(src_inc_GL_internal, target_inc_GL_internal)
            self.log.info("Copied %s to %s" % (src_inc_GL_internal, target_inc_GL_internal))

    def sanity_check_step(self):
        """Custom sanity check for Mesa."""

        shlib_ext = get_shared_lib_ext()

        if LooseVersion(self.version) >= LooseVersion('20.0'):
            header_files = [os.path.join('include', 'EGL', 'eglmesaext.h')]
            if LooseVersion(self.version) >= LooseVersion('22.3'):
                header_files.extend([os.path.join('include', 'EGL', 'eglext_angle.h')])
            else:
                header_files.extend([os.path.join('include', 'EGL', 'eglextchromium.h')])
            header_files.extend([
                os.path.join('include', 'GL', 'osmesa.h'),
                os.path.join('include', 'GL', 'internal', 'dri_interface.h'),
            ])
        else:
            gl_inc_files = ['glext.h', 'gl_mangle.h', 'glx.h', 'osmesa.h', 'gl.h', 'glxext.h', 'glx_mangle.h']
            gles_inc_files = [('GLES', 'gl.h'), ('GLES2', 'gl2.h'), ('GLES3', 'gl3.h')]
            header_files = [os.path.join('include', 'GL', x) for x in gl_inc_files]
            header_files.extend([os.path.join('include', x, y) for (x, y) in gles_inc_files])

        custom_paths = {
            'files': [os.path.join('lib', 'libOSMesa.%s' % shlib_ext)] + header_files,
            'dirs': [os.path.join('include', 'GL', 'internal')],
        }

        if self.swr_arches:
            swr_arch_libs = [os.path.join('lib', 'libswr%s.%s' % (a.upper(), shlib_ext)) for a in self.swr_arches]
            custom_paths['files'].extend(swr_arch_libs)

        super(EB_Mesa, self).sanity_check_step(custom_paths=custom_paths)

    def make_module_extra(self, *args, **kwargs):
        """ Append to EGL vendor library path,
        so that any NVidia libraries take precedence. """
        txt = super(EB_Mesa, self).make_module_extra(*args, **kwargs)
        # Append rather than prepend path to ensure that system NVidia drivers have priority.
        txt += self.module_generator.append_paths('__EGL_VENDOR_LIBRARY_DIRS', 'share/glvnd/egl_vendor.d')
        return txt
