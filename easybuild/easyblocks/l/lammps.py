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

import glob
import shutil
import sys, os
from easybuild.easyblocks.generic.makecp import MakeCp
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import apply_regex_substitutions
from easybuild.tools.modules import get_software_root
from easybuild.tools.run import run_cmd
import easybuild.tools.toolchain as toolchain

class EB_LAMMPS(MakeCp):
    """
    Support for building and installing LAMMPS
    """

    @staticmethod
    def extra_options(extra_vars=None):
        """Extra easyconfig parameters specific to ConfigureMake."""
        extra_vars = MakeCp.extra_options(extra_vars=extra_vars)
        extra_vars.update({
            'with_png': [False, "Support export of PNG files (only valid with MPI)", CUSTOM],
            'with_jpeg': [False, "Support export of JPEG files (only valid with MPI)", CUSTOM],
            'standard_packages': [[], "Optional \"standard\" packages to include", CUSTOM],
            'user_packages': [[], "Optional user-supplied packages to include", CUSTOM],
            'gpu_base_makefile': ['Makefile.linux', "Makefile to use when generating GPU build instructions", CUSTOM],
            'gpu_arch_string': ['sm_20', "Architecture code to use when generating GPU build instructions", CUSTOM],
            'gpu_prec_string': ['mixed', "Precision to use when generating GPU build instructions", CUSTOM],
            'cuda_prec_val': [1, "Numeric code designating the precision to which to build the CUDA library", CUSTOM],
            'cuda_arch_val': [20, "Numeric code designating the CUDA architecture to use", CUSTOM],
            'cuda_use_prec_timers': [False, "Use high-precision timers when building the CUDA library", CUSTOM],
            'cuda_use_debug': [False, "Enable debug mode in the CUDA library", CUSTOM],
            'cuda_use_cufft': [False, "Enable CUDA FFT library", CUSTOM],
        })
        return extra_vars

    def build_step(self, verbose=False, path=None):
        """
        Start the actual build
        - typical: make -j X
        """

        # Can't be None as needs to be appended to
        out = ''
        src_dir = os.path.join(self.cfg['start_dir'], 'src')
        cudaroot = get_software_root('CUDA')

        if self.toolchain.options.get('openmp', None):
            self.cfg['user_packages'].append('omp')
        
        for std_package in self.cfg['standard_packages']:

            if std_package == 'gpu':
                gpu_lib_dir = os.path.join(self.cfg['start_dir'], 'lib', 'gpu')
                os.chdir(gpu_lib_dir)

                precstring = 'SINGLE_DOUBLE'
                if self.cfg['gpu_prec_string'] == 'double':
                    precstring = 'DOUBLE_DOUBLE'
                elif self.cfg['gpu_prec_string'] == 'single':
                    precstring = 'SINGLE_SINGLE'
                elif self.cfg['gpu_prec_string'] != 'mixed':
                    raise EasyBuildError("Don't know how to handle GPU precision style: %s" % self.cfg['gpu_prec_string'])

                if cudaroot:
                    apply_regex_substitutions(self.cfg['gpu_base_makefile'], [
                        (r'^(CUDA_HOME\s*=\s*).*$', r'\1%s' % cudaroot),
                        (r'^(CUDA_ARCH\s*=\s*-arch=).*$', r'\1%s' % self.cfg['gpu_arch_string']),
                        (r'^(CUDA_LIB\s*=\s*)(-L\S*)(.*)$', r'\1\2 \2/stubs\3'),
                        (r'^(CUDA_PRECISION\s*=\s*-D_).*$', r'\1%s' % precstring),
                    ])
                else:
                    raise EasyBuildError("Could not get CUDA root -- module not loaded?")
                    
                cmd = "{0} make -f {1} {2}".format(
                        self.cfg['prebuildopts'],
                        self.cfg['gpu_base_makefile'],
                        self.cfg['buildopts'],
                        )
                (gpu_lib_output, _) = run_cmd(cmd, path=path, log_all=True, simple=False, log_output=verbose)
                out += gpu_lib_output

            elif std_package == 'meam':
                meam_lib_dir = os.path.join(self.cfg['start_dir'], 'lib', 'meam')
                os.chdir(meam_lib_dir)
                if self.toolchain.comp_family() in [toolchain.GCC]:
                    meam_suffix = 'gfortran'
                elif self.toolchain.comp_family() in [toolchain.INTELCOMP]:
                    meam_suffix = 'ifort'
                else:
                    raise EasyBuildError("Don't know how to compile meam with compiler {0}".format(self.toolchain.comp_family()))

                cmd = "{0} make -f Makefile.{1} {2}".format(self.cfg['prebuildopts'], meam_suffix, self.cfg['buildopts'])
                (meam_lib_output, _) = run_cmd(cmd, path=path, log_all=True, simple=False, log_output=verbose)
                out += meam_lib_output

                # Tweak the resulting Makefile.lammps
                if self.toolchain.comp_family() in [toolchain.INTELCOMP]:
                    apply_regex_substitutions('Makefile.lammps', [
                            (r'^(meam_SYSLIB\s*=.*\s+)-lompstub\s+(.*)$', r'\1\2'),
                            (r'^(meam_SYSPATH\s*=\s*-L).*$', r'\1%s' % os.getenv('EBROOTIFORT'))
                        ])

            # Do these steps in any event
            os.chdir(src_dir)
            (stdout_text, _) = run_cmd("make yes-{0}".format(std_package), path=path, log_all=True, simple=False, log_output=verbose)
            out += stdout_text

        for user_package in self.cfg['user_packages']:
            if user_package == 'cuda':
                cuda_lib_dir = os.path.join(self.cfg['start_dir'], 'lib', 'cuda')
                os.chdir(cuda_lib_dir)
                cmd = "{0} make precision={1} arch={2} prec_timer={3} dbg={4} cufft={5} {6}".format(
                        self.cfg['prebuildopts'],
                        self.cfg['cuda_prec_val'],
                        self.cfg['cuda_arch_val'],
                        int(self.cfg['cuda_use_prec_timers']),
                        int(self.cfg['cuda_use_debug']),
                        int(self.cfg['cuda_use_cufft']),
                        self.cfg['buildopts'],
                        )
                (cuda_lib_output_1, _) = run_cmd(cmd, path=path, log_all=True, simple=False, log_output=verbose)
                out += cuda_lib_output_1
                cmd = "{0} make {1}".format(self.cfg['prebuildopts'], self.cfg['buildopts'])
                (cuda_lib_output_2, _) = run_cmd(cmd, path=path, log_all=True, simple=False, log_output=verbose)
                out += cuda_lib_output_2
            #elif user_package == 'foo':
            #    #TODO: other stuff

            # Do these steps in any event
            os.chdir(src_dir)
            (stdout_text, _) = run_cmd("make yes-user-{0}".format(user_package), path=path, log_all=True, simple=False, log_output=verbose)
            out += stdout_text

        # Go back to the main directory (we should be there, but just make sure)
        os.chdir(src_dir)

        makedir = os.path.join(src_dir, 'MAKE')
        makearg = 'serial'
        makesubs = []

        if self.toolchain.options.get('usempi', None):
            makearg = 'mpi'

            if self.toolchain.comp_family() in [toolchain.INTELCOMP]:
                makedir = os.path.join(makedir, 'OPTIONS')
                makearg = 'intel_cpu'
            elif self.cfg['with_png'] and not self.cfg['with_jpeg']:
                makedir = os.path.join(makedir, 'OPTIONS')
                makearg = 'png'

            if self.cfg['with_png'] and not self.cfg['with_jpeg']:
                libpngroot = get_software_root('libpng')
                if libpngroot:
                    makesubs = [
                        (r'^(LMP_INC.*)-DLAMMPS_JPEG', r'\1-DLAMMPS_PNG'),
                        (r'^(JPG_LIB.*)-ljpeg', r'\1-lpng'),
                        (r'^(JPG_INC\s*=\s*).*(\n)', r'\1%s/include\2' % libpngroot),
                        (r'^(JPG_PATH\s*=\s*).*(\n)', r'\1-L%s/lib\2' % libpngroot),
                    ]
                else:
                    raise EasyBuildError("Unable to find libpng root -- module not loaded?")
            elif self.cfg['with_jpeg'] and not self.cfg['with_png']:
                makedir = os.path.join(makedir, 'OPTIONS')
                makearg = 'jpeg'
            elif self.cfg['with_jpeg'] and self.cfg['with_png']:
                raise EasyBuildError("Use either with_jpeg or with_png, but not both.")
        
        makesubs.extend([(r'^(CCFLAGS\s*=\s*)(.*)$', r'\1%s \2' % os.getenv('CFLAGS'))])
        if cudaroot:
            makesubs.extend([(r'^(LINKFLAGS\s*=\s*)(.*)$', r'\1%s -L%s/lib64/stubs \2' % (os.getenv('LDFLAGS'), cudaroot))])
        else:
            makesubs.extend([(r'^(LINKFLAGS\s*=\s*)(.*)$', r'\1%s \2' % os.getenv('LDFLAGS'))])

        apply_regex_substitutions(os.path.join(makedir, 'Makefile.{0}'.format(makearg)), makesubs)

        os.chdir(src_dir)
        cmd = "{0} make {1} {2}".format(self.cfg['prebuildopts'], makearg, self.cfg['buildopts'])
        (main_make_output, _) = run_cmd(cmd, path=path, log_all=True, simple=False, log_output=verbose)
        out += main_make_output
        
        return out

    def install_step(self):
        """
        Install the executable
        """
        binpath = os.path.join(self.installdir, 'bin')
        os.makedirs(binpath)

        super(EB_LAMMPS, self).install_step()
        executables = os.listdir(binpath)
        if len(executables) == 1:
            os.chdir(binpath)
            os.symlink(executables[0], 'lammps')
        elif len(executables) == 0:
            raise EasyBuildError("No LAMMPS executables found!")
        else:
            self.log.warning("Multiple LAMMPS executables found -- unsure which to use as primary")

    def sanity_check_step(self):
        """Custom sanity check for LAMMPS."""
        custom_paths = {
            'files': [],
            'dirs': ['bin'],
        }
        super(EB_LAMMPS, self).sanity_check_step(custom_paths=custom_paths)
