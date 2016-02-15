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
            'use_asphere': [False, "Include the optional, standard \"asphere\" package", CUSTOM],
            'use_body': [False, "Include the optional, standard \"body\" package", CUSTOM],
            'use_class2': [False, "Include the optional, standard \"class2\" package", CUSTOM],
            'use_colloid': [False, "Include the optional, standard \"colloid\" package", CUSTOM],
            'use_compress': [False, "Include the optional, standard \"compress\" package", CUSTOM],
            'use_coreshell': [False, "Include the optional, standard \"coreshell\" package", CUSTOM],
            'use_dipole': [False, "Include the optional, standard \"dipole\" package", CUSTOM],
            'use_fld': [False, "Include the optional, standard \"fld\" package", CUSTOM],
            'use_gpu': [False, "Include the optional, standard \"gpu\" package", CUSTOM],
            'use_granular': [False, "Include the optional, standard \"granular\" package", CUSTOM],
            'use_kim': [False, "Include the optional, standard \"kim\" package", CUSTOM],
            'use_kokkos': [False, "Include the optional, standard \"kokkos\" package", CUSTOM],
            'use_kspace': [False, "Include the optional, standard \"kspace\" package", CUSTOM],
            'use_manybody': [False, "Include the optional, standard \"manybody\" package", CUSTOM],
            'use_mc': [False, "Include the optional, standard \"mc\" package", CUSTOM],
            'use_meam': [False, "Include the optional, standard \"meam\" package", CUSTOM],
            'use_misc': [False, "Include the optional, standard \"misc\" package", CUSTOM],
            'use_molecule': [False, "Include the optional, standard \"molecule\" package", CUSTOM],
            'use_mpiio': [False, "Include the optional, standard \"mpiio\" package", CUSTOM],
            'use_opt': [False, "Include the optional, standard \"opt\" package", CUSTOM],
            'use_peri': [False, "Include the optional, standard \"peri\" package", CUSTOM],
            'use_poems': [False, "Include the optional, standard \"poems\" package", CUSTOM],
            'use_python': [False, "Include the optional, standard \"python\" package", CUSTOM],
            'use_qeq': [False, "Include the optional, standard \"qeq\" package", CUSTOM],
            'use_reax': [False, "Include the optional, standard \"reax\" package", CUSTOM],
            'use_replica': [False, "Include the optional, standard \"replica\" package", CUSTOM],
            'use_rigid': [False, "Include the optional, standard \"rigid\" package", CUSTOM],
            'use_shock': [False, "Include the optional, standard \"shock\" package", CUSTOM],
            'use_snap': [False, "Include the optional, standard \"snap\" package", CUSTOM],
            'use_srd': [False, "Include the optional, standard \"srd\" package", CUSTOM],
            'use_voronoi': [False, "Include the optional, standard \"voronoi\" package", CUSTOM],
            'use_xtc': [False, "Include the optional, standard \"xtc\" package", CUSTOM],
            'use_atc': [False, "Include the optional, user-contributed \"user-atc\" package", CUSTOM],
            'use_awpmd': [False, "Include the optional, user-contributed \"user-awpmd\" package", CUSTOM],
            'use_cg_cmm': [False, "Include the optional, user-contributed \"user-cg-cmm\" package", CUSTOM],
            'use_colvars': [False, "Include the optional, user-contributed \"user-colvars\" package", CUSTOM],
            'use_cuda': [False, "Include the optional, user-contributed \"user-cuda\" package", CUSTOM],
            'use_diffraction': [False, "Include the optional, user-contributed \"user-diffraction\" package", CUSTOM],
            'use_drude': [False, "Include the optional, user-contributed \"user-drude\" package", CUSTOM],
            'use_eff': [False, "Include the optional, user-contributed \"user-eff\" package", CUSTOM],
            'use_fep': [False, "Include the optional, user-contributed \"user-fep\" package", CUSTOM],
            'use_h5md': [False, "Include the optional, user-contributed \"user-h5md\" package", CUSTOM],
            'use_intel': [False, "Include the optional, user-contributed \"user-intel\" package", CUSTOM],
            'use_lb': [False, "Include the optional, user-contributed \"user-lb\" package", CUSTOM],
            'use_mgpt': [False, "Include the optional, user-contributed \"user-mgpt\" package", CUSTOM],
            'use_misc': [False, "Include the optional, user-contributed \"user-misc\" package", CUSTOM],
            'use_molfile': [False, "Include the optional, user-contributed \"user-molfile\" package", CUSTOM],
            'use_omp': [False, "Include the optional, user-contributed \"user-omp\" package", CUSTOM],
            'use_phonon': [False, "Include the optional, user-contributed \"user-phonon\" package", CUSTOM],
            'use_qmmm': [False, "Include the optional, user-contributed \"user-qmmm\" package", CUSTOM],
            'use_qtb': [False, "Include the optional, user-contributed \"user-qtb\" package", CUSTOM],
            'use_quip': [False, "Include the optional, user-contributed \"user-quip\" package", CUSTOM],
            'use_reaxc': [False, "Include the optional, user-contributed \"user-reaxc\" package", CUSTOM],
            'use_smd': [False, "Include the optional, user-contributed \"user-smd\" package", CUSTOM],
            'use_smtbq': [False, "Include the optional, user-contributed \"user-smtbq\" package", CUSTOM],
            'use_sph': [False, "Include the optional, user-contributed \"user-sph\" package", CUSTOM],
            'use_tally': [False, "Include the optional, user-contributed \"user-tally\" package", CUSTOM],
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

    def build_asphere(self, verbose=False, path=None):
        """
        Build the asphere package
        """
        raise EasyBuildError("No instructions yet for building the asphere package.")

    def build_body(self, verbose=False, path=None):
        """
        Build the body package
        """
        os.chdir(os.path.join(self.cfg['start_dir'], 'src'))
        cmd = "make yes-body"
        (body_src_output, _) = run_cmd(cmd, path=path, log_all=True, simple=False, log_output=verbose)
        return body_src_output

    def build_class2(self, verbose=False, path=None):
        """
        Build the class2 package
        """
        raise EasyBuildError("No instructions yet for building the class2 package.")

    def build_colloid(self, verbose=False, path=None):
        """
        Build the colloid package
        """
        raise EasyBuildError("No instructions yet for building the colloid package.")

    def build_compress(self, verbose=False, path=None):
        """
        Build the compress package
        """
        raise EasyBuildError("No instructions yet for building the compress package.")

    def build_coreshell(self, verbose=False, path=None):
        """
        Build the coreshell package
        """
        raise EasyBuildError("No instructions yet for building the coreshell package.")

    def build_dipole(self, verbose=False, path=None):
        """
        Build the dipole package
        """
        raise EasyBuildError("No instructions yet for building the dipole package.")

    def build_fld(self, verbose=False, path=None):
        """
        Build the fld package
        """
        raise EasyBuildError("No instructions yet for building the fld package.")

    def build_gpu(self, verbose=False, path=None):
        """
        Build the gpu package
        """
        gpu_lib_dir = os.path.join(self.cfg['start_dir'], 'lib', 'gpu')
        os.chdir(gpu_lib_dir)

        precstring = 'SINGLE_DOUBLE'
        if self.cfg['gpu_prec_string'] == 'double':
            precstring = 'DOUBLE_DOUBLE'
        elif self.cfg['gpu_prec_string'] == 'single':
            precstring = 'SINGLE_SINGLE'
        elif self.cfg != 'mixed':
            raise EasyBuildError("Don't know how to handle GPU precision style: %s" % self.cfg['gpu_prec_string'])

        cudaroot = get_software_root('CUDA')
        if cudaroot:
            apply_regex_substitutions(self.cfg['gpu_base_makefile'], [
                (r'\$\(CUDA_HOME\)', cudaroot),
                (r'^(CUDA_ARCH\s*=\s*-arch=).*$', r'\1%s' % self.cfg['gpu_arch_string']),
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
        
        os.chdir(os.path.join(self.cfg['start_dir'], 'src'))
        cmd = "make yes-gpu"
        (gpu_src_output, _) = run_cmd(cmd, path=path, log_all=True, simple=False, log_output=verbose)

        return (gpu_lib_output + gpu_src_output)

    def build_granular(self, verbose=False, path=None):
        """
        Build the granular package
        """
        os.chdir(os.path.join(self.cfg['start_dir'], 'src'))
        cmd = "make yes-granular"
        (granular_src_output, _) = run_cmd(cmd, path=path, log_all=True, simple=False, log_output=verbose)
        return granular_src_output

    def build_kim(self, verbose=False, path=None):
        """
        Build the kim package
        """
        raise EasyBuildError("No instructions yet for building the kim package.")

    def build_kokkos(self, verbose=False, path=None):
        """
        Build the kokkos package
        """
        raise EasyBuildError("No instructions yet for building the kokkos package.")

    def build_kspace(self, verbose=False, path=None):
        """
        Build the kspace package
        """
        raise EasyBuildError("No instructions yet for building the kspace package.")

    def build_manybody(self, verbose=False, path=None):
        """
        Build the manybody package
        """
        raise EasyBuildError("No instructions yet for building the manybody package.")

    def build_mc(self, verbose=False, path=None):
        """
        Build the mc package
        """
        raise EasyBuildError("No instructions yet for building the mc package.")

    def build_meam(self, verbose=False, path=None):
        """
        Build the meam package and supporting library
        """
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

        # Tweak the resulting Makefile.lammps
        if self.toolchain.comp_family() in [toolchain.INTELCOMP]:
            apply_regex_substitutions('Makefile.lammps', [
                (r'^(meam_SYSLIB\s*=.*\s+)-lompstub\s+(.*)$', r'\1\2'),
                (r'^(meam_SYSPATH\s*=\s*-L).*$', r'\1%s' % os.getenv('EBROOTIFORT'))
            ])

        os.chdir(os.path.join(self.cfg['start_dir'], 'src'))
        cmd = "make yes-meam"
        (meam_src_output, _) = run_cmd(cmd, path=path, log_all=True, simple=False, log_output=verbose)

        return (meam_lib_output + meam_src_output)

    def build_misc(self, verbose=False, path=None):
        """
        Build the misc package
        """
        raise EasyBuildError("No instructions yet for building the misc package.")

    def build_molecule(self, verbose=False, path=None):
        """
        Build the molecule package
        """
        raise EasyBuildError("No instructions yet for building the molecule package.")

    def build_mpiio(self, verbose=False, path=None):
        """
        Build the mpiio package
        """
        raise EasyBuildError("No instructions yet for building the mpiio package.")

    def build_opt(self, verbose=False, path=None):
        """
        Build the opt package
        """
        raise EasyBuildError("No instructions yet for building the opt package.")

    def build_peri(self, verbose=False, path=None):
        """
        Build the peri package
        """
        raise EasyBuildError("No instructions yet for building the peri package.")

    def build_poems(self, verbose=False, path=None):
        """
        Build the poems package
        """
        raise EasyBuildError("No instructions yet for building the poems package.")

    def build_python(self, verbose=False, path=None):
        """
        Build the python package
        """
        os.chdir(os.path.join(self.cfg['start_dir'], 'src'))
        cmd = "make yes-python"
        (python_src_output, _) = run_cmd(cmd, path=path, log_all=True, simple=False, log_output=verbose)
        return python_src_output

    def build_qeq(self, verbose=False, path=None):
        """
        Build the qeq package
        """
        raise EasyBuildError("No instructions yet for building the qeq package.")

    def build_reax(self, verbose=False, path=None):
        """
        Build the reax package
        """
        raise EasyBuildError("No instructions yet for building the reax package.")

    def build_replica(self, verbose=False, path=None):
        """
        Build the replica package
        """
        raise EasyBuildError("No instructions yet for building the replica package.")

    def build_rigid(self, verbose=False, path=None):
        """
        Build the rigid package
        """
        os.chdir(os.path.join(self.cfg['start_dir'], 'src'))
        cmd = "make yes-rigid"
        (rigid_src_output, _) = run_cmd(cmd, path=path, log_all=True, simple=False, log_output=verbose)
        return rigid_src_output

    def build_shock(self, verbose=False, path=None):
        """
        Build the shock package
        """
        raise EasyBuildError("No instructions yet for building the shock package.")

    def build_snap(self, verbose=False, path=None):
        """
        Build the snap package
        """
        raise EasyBuildError("No instructions yet for building the snap package.")

    def build_srd(self, verbose=False, path=None):
        """
        Build the srd package
        """
        os.chdir(os.path.join(self.cfg['start_dir'], 'src'))
        cmd = "make yes-srd"
        (srd_src_output, _) = run_cmd(cmd, path=path, log_all=True, simple=False, log_output=verbose)
        return srd_src_output

    def build_voronoi(self, verbose=False, path=None):
        """
        Build the voronoi package
        """
        raise EasyBuildError("No instructions yet for building the voronoi package.")

    def build_xtc(self, verbose=False, path=None):
        """
        Build the xtc package
        """
        raise EasyBuildError("No instructions yet for building the xtc package.")

    def build_user_atc(self, verbose=False, path=None):
        """
        Build the user-atc package
        """
        raise EasyBuildError("No instructions yet for building the user-atc package.")

    def build_user_awpmd(self, verbose=False, path=None):
        """
        Build the user-awpmd package
        """
        raise EasyBuildError("No instructions yet for building the user-awpmd package.")

    def build_user_cg_cmm(self, verbose=False, path=None):
        """
        Build the user-cg-cmm package
        """
        raise EasyBuildError("No instructions yet for building the user-cg-cmm package.")

    def build_user_colvars(self, verbose=False, path=None):
        """
        Build the user-colvars package
        """
        raise EasyBuildError("No instructions yet for building the user-colvars package.")

    def build_user_cuda(self, verbose=False, path=None):
        """
        Build the user-cuda package
        """
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
        cmd = "{0} make {1}".format(self.cfg['prebuildopts'], self.cfg['buildopts'])
        (cuda_lib_output_2, _) = run_cmd(cmd, path=path, log_all=True, simple=False, log_output=verbose)
        
        os.chdir(os.path.join(self.cfg['start_dir'], 'src'))
        cmd = "make yes-user-cuda"
        (cuda_src_output, _) = run_cmd(cmd, path=path, log_all=True, simple=False, log_output=verbose)

        return (cuda_lib_output_1 + cuda_lib_output_2 + cuda_src_output)

    def build_user_diffraction(self, verbose=False, path=None):
        """
        Build the user-diffraction package
        """
        raise EasyBuildError("No instructions yet for building the user-diffraction package.")

    def build_user_drude(self, verbose=False, path=None):
        """
        Build the user-drude package
        """
        raise EasyBuildError("No instructions yet for building the user-drude package.")

    def build_user_eff(self, verbose=False, path=None):
        """
        Build the user-eff package
        """
        raise EasyBuildError("No instructions yet for building the user-eff package.")

    def build_user_fep(self, verbose=False, path=None):
        """
        Build the user-fep package
        """
        raise EasyBuildError("No instructions yet for building the user-fep package.")

    def build_user_h5md(self, verbose=False, path=None):
        """
        Build the user-h5md package
        """
        raise EasyBuildError("No instructions yet for building the user-h5md package.")

    def build_user_intel(self, verbose=False, path=None):
        """
        Build the user-intel package
        """
        os.chdir(os.path.join(self.cfg['start_dir'], 'src'))
        cmd = "make yes-user-intel"
        (user_intel_src_output, _) = run_cmd(cmd, path=path, log_all=True, simple=False, log_output=verbose)
        return user_intel_src_output

    def build_user_lb(self, verbose=False, path=None):
        """
        Build the user-lb package
        """
        os.chdir(os.path.join(self.cfg['start_dir'], 'src'))
        cmd = "make yes-user-lb"
        (user_lb_src_output, _) = run_cmd(cmd, path=path, log_all=True, simple=False, log_output=verbose)
        return user_lb_src_output

    def build_user_mgpt(self, verbose=False, path=None):
        """
        Build the user-mgpt package
        """
        raise EasyBuildError("No instructions yet for building the user-mgpt package.")

    def build_user_misc(self, verbose=False, path=None):
        """
        Build the user-misc package
        """
        raise EasyBuildError("No instructions yet for building the user-misc package.")

    def build_user_molfile(self, verbose=False, path=None):
        """
        Build the user-molfile package
        """
        raise EasyBuildError("No instructions yet for building the user-molfile package.")

    def build_user_omp(self, verbose=False, path=None):
        """
        Build the user-omp package
        """
        os.chdir(os.path.join(self.cfg['start_dir'], 'src'))
        cmd = "make yes-user-omp"
        (user_omp_src_output, _) = run_cmd(cmd, path=path, log_all=True, simple=False, log_output=verbose)
        return user_omp_src_output

    def build_user_phonon(self, verbose=False, path=None):
        """
        Build the user-phonon package
        """
        raise EasyBuildError("No instructions yet for building the user-phonon package.")

    def build_user_qmmm(self, verbose=False, path=None):
        """
        Build the user-qmmm package
        """
        raise EasyBuildError("No instructions yet for building the user-qmmm package.")

    def build_user_qtb(self, verbose=False, path=None):
        """
        Build the user-qtb package
        """
        raise EasyBuildError("No instructions yet for building the user-qtb package.")

    def build_user_quip(self, verbose=False, path=None):
        """
        Build the user-quip package
        """
        raise EasyBuildError("No instructions yet for building the user-quip package.")

    def build_user_reaxc(self, verbose=False, path=None):
        """
        Build the user-reaxc package
        """
        raise EasyBuildError("No instructions yet for building the user-reaxc package.")

    def build_user_smd(self, verbose=False, path=None):
        """
        Build the user-smd package
        """
        raise EasyBuildError("No instructions yet for building the user-smd package.")

    def build_user_smtbq(self, verbose=False, path=None):
        """
        Build the user-smtbq package
        """
        raise EasyBuildError("No instructions yet for building the user-smtbq package.")

    def build_user_sph(self, verbose=False, path=None):
        """
        Build the user-sph package
        """
        raise EasyBuildError("No instructions yet for building the user-sph package.")

    def build_user_tally(self, verbose=False, path=None):
        """
        Build the user-tally package
        """
        raise EasyBuildError("No instructions yet for building the user-tally package.")

    def build_step(self, verbose=False, path=None):
        """
        Start the actual build
        - typical: make -j X
        """

        # Can't be None as needs to be appended to
        out = ''
        src_dir = os.path.join(self.cfg['start_dir'], 'src')

        if self.toolchain.options.get('openmp', None):
            out += self.build_user_omp(verbose, path)

        if self.cfg['use_asphere']:
            out += self.build_asphere(verbose, path)

        if self.cfg['use_body']:
            out += self.build_body(verbose, path)

        if self.cfg['use_class2']:
            out += self.build_class2(verbose, path)

        if self.cfg['use_colloid']:
            out += self.build_colloid(verbose, path)

        if self.cfg['use_compress']:
            out += self.build_compress(verbose, path)

        if self.cfg['use_coreshell']:
            out += self.build_coreshell(verbose, path)

        if self.cfg['use_dipole']:
            out += self.build_dipole(verbose, path)

        if self.cfg['use_fld']:
            out += self.build_fld(verbose, path)

        if self.cfg['use_gpu']:
            out += self.build_gpu(verbose, path)

        if self.cfg['use_granular']:
            out += self.build_granular(verbose, path)

        if self.cfg['use_kim']:
            out += self.build_kim(verbose, path)

        if self.cfg['use_kokkos']:
            out += self.build_kokkos(verbose, path)

        if self.cfg['use_kspace']:
            out += self.build_kspace(verbose, path)

        if self.cfg['use_manybody']:
            out += self.build_manybody(verbose, path)

        if self.cfg['use_mc']:
            out += self.build_mc(verbose, path)

        if self.cfg['use_meam']:
            out += self.build_meam(verbose, path)

        if self.cfg['use_misc']:
            out += self.build_misc(verbose, path)

        if self.cfg['use_molecule']:
            out += self.build_molecule(verbose, path)

        if self.cfg['use_mpiio']:
            out += self.build_mpiio(verbose, path)

        if self.cfg['use_opt']:
            out += self.build_opt(verbose, path)

        if self.cfg['use_peri']:
            out += self.build_peri(verbose, path)

        if self.cfg['use_poems']:
            out += self.build_poems(verbose, path)

        if self.cfg['use_python']:
            out += self.build_python(verbose, path)

        if self.cfg['use_qeq']:
            out += self.build_qeq(verbose, path)

        if self.cfg['use_reax']:
            out += self.build_reax(verbose, path)

        if self.cfg['use_replica']:
            out += self.build_replica(verbose, path)

        if self.cfg['use_rigid']:
            out += self.build_rigid(verbose, path)

        if self.cfg['use_shock']:
            out += self.build_shock(verbose, path)

        if self.cfg['use_snap']:
            out += self.build_snap(verbose, path)

        if self.cfg['use_srd']:
            out += self.build_srd(verbose, path)

        if self.cfg['use_voronoi']:
            out += self.build_voronoi(verbose, path)

        if self.cfg['use_xtc']:
            out += self.build_xtc(verbose, path)

        if self.cfg['use_atc']:
            out += self.build_user_atc(verbose, path)

        if self.cfg['use_awpmd']:
            out += self.build_user_awpmd(verbose, path)

        if self.cfg['use_cg_cmm']:
            out += self.build_user_cg_cmm(verbose, path)

        if self.cfg['use_colvars']:
            out += self.build_user_colvars(verbose, path)

        if self.cfg['use_cuda']:
            out += self.build_user_cuda(verbose, path)

        if self.cfg['use_diffraction']:
            out += self.build_user_diffraction(verbose, path)

        if self.cfg['use_drude']:
            out += self.build_user_drude(verbose, path)

        if self.cfg['use_eff']:
            out += self.build_user_eff(verbose, path)

        if self.cfg['use_fep']:
            out += self.build_user_fep(verbose, path)

        if self.cfg['use_h5md']:
            out += self.build_user_h5md(verbose, path)

        if self.cfg['use_intel']:
            out += self.build_user_intel(verbose, path)

        if self.cfg['use_lb']:
            out += self.build_user_lb(verbose, path)

        if self.cfg['use_mgpt']:
            out += self.build_user_mgpt(verbose, path)

        if self.cfg['use_misc']:
            out += self.build_user_misc(verbose, path)

        if self.cfg['use_molfile']:
            out += self.build_user_molfile(verbose, path)

        if self.cfg['use_phonon']:
            out += self.build_user_phonon(verbose, path)

        if self.cfg['use_qmmm']:
            out += self.build_user_qmmm(verbose, path)

        if self.cfg['use_qtb']:
            out += self.build_user_qtb(verbose, path)

        if self.cfg['use_quip']:
            out += self.build_user_quip(verbose, path)

        if self.cfg['use_reaxc']:
            out += self.build_user_reaxc(verbose, path)

        if self.cfg['use_smd']:
            out += self.build_user_smd(verbose, path)

        if self.cfg['use_smtbq']:
            out += self.build_user_smtbq(verbose, path)

        if self.cfg['use_sph']:
            out += self.build_user_sph(verbose, path)

        if self.cfg['use_tally']:
            out += self.build_user_tally(verbose, path)

        # Go back to the main directory
        os.chdir(src_dir)

        makedir = os.path.join(src_dir, 'MAKE')
        makearg = 'serial'
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
        
        makesubs.extend([
            (r'^(CCFLAGS\s*=\s*)(.*)$', r'\1%s \2' % os.getenv('CFLAGS')),
            (r'^(LINKFLAGS\s*=\s*)(.*)$', r'\1%s \2' % os.getenv('LDFLAGS')),
        ])
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
