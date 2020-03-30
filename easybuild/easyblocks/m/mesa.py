##
# Copyright 2009-2020 Ghent University
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
from distutils.version import LooseVersion

from easybuild.easyblocks.generic.mesonninja import MesonNinja
from easybuild.tools.filetools import copy_dir
from easybuild.tools.systemtools import POWER, X86_64, get_cpu_architecture, get_cpu_features, get_shared_lib_ext


class EB_Mesa(MesonNinja):
    """Custom easyblock for building and installing Mesa."""

    def get_configopt_values(self, opt_name):
        """Get list of values given to a multi-value option like -DFOO=bar,baz"""
        option = [opt for opt in self.cfg['configopts'].split() if opt.startswith('-D%s=' % opt_name)]
        if option:
            # Get value of last option added
            value = option[-1].split('=')[-1]
            # Remove quotes and extract individual values
            result = value.strip('"\'').split(',')
        else:
            result = None
        return result

    def configure_step(self):
        """
        Customise the configure options based on the processor architecture of the host
        (x86_64 or not, CPU features, ...)
        """

        gallium_drivers = self.get_configopt_values('gallium-drivers')
        if gallium_drivers is None:
            # Install appropriate Gallium drivers for current architecture
            arch = get_cpu_architecture()
            if arch == X86_64:
                gallium_drivers = ['swrast', 'swr']
            elif arch == POWER:
                gallium_drivers = ['swrast']
            self.cfg.update('configopts', "-Dgallium-drivers='%s'" % ','.join(gallium_drivers))

        if 'swr' in gallium_drivers and self.get_configopt_values('swr-arches') is None:
            # set cpu features of SWR for current architecture
            feat_to_swrarch = {
                'avx': 'avx',
                'avx1.0': 'avx',  # on macOS, AVX is indicated with 'avx1.0' rather than 'avx'
                'avx2': 'avx2',
                'avx512f': 'skx',  # AVX-512 Foundation - introduced in Skylake
                'avx512er': 'knl',  # AVX-512 Exponential and Reciprocal Instructions implemented in Knights Landing
            }
            # determine list of values to pass to swr-arches configuration option
            cpu_features = get_cpu_features()
            swr_arches = [swrarch for feat, swrarch in feat_to_swrarch.items() if feat in cpu_features]
            self.cfg.update('configopts', '-Dswr-arches=' + ','.join(swr_arches))

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
            header_files = [os.path.join('include', 'EGL', x) for x in ['eglmesaext.h', 'eglextchromium.h']]
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

        gallium_drivers = self.get_configopt_values('gallium-drivers')
        self.log.debug('Gallium driver(s) built: %s' % gallium_drivers)

        if 'swr' in gallium_drivers:
            swr_arches = self.get_configopt_values('swr-arches')
            self.log.debug('SWR gallium driver built for %s' % swr_arches)
            if swr_arches:
                swr_arch_libs = [os.path.join('lib', 'libswr%s.%s' % (a.upper(), shlib_ext)) for a in swr_arches]
                custom_paths['files'].extend(swr_arch_libs)

        super(EB_Mesa, self).sanity_check_step(custom_paths=custom_paths)
