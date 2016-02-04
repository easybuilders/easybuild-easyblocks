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

from easybuild.framework.easyblock import EasyBlock
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.filetools import apply_regex_substitutions
from easybuild.tools.run import run_cmd

class EB_LAMMPS(EasyBlock):
    """
    Support for building and installing LAMMPS
    """

    @staticmethod
    def extra_options(extra_vars=None):
        """Extra easyconfig parameters specific to ConfigureMake."""
        extra_vars = EasyBlock.extra_options(extra=extra_vars)
        colloid compress coreshell dipole fld gpu granular kim kokkos kspace manybody mc meam misc molecule mpiio opt peri poems python qeq reax replica rigid shock snap srd voronoi xtc
        extra_vars.update({
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
            'use_cg-cmm': [False, "Include the optional, user-contributed \"user-cg-cmm\" package", CUSTOM],
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
        })
        return extra_vars

    def configure_step(self, cmd_prefix=''):
        """
        No separate configure step is necessary
        """
        pass

    def build_meam(self):
        """
        Build the meam library
        """
        meam_dir = os.path.join(self.cfg['start_dir'], 'lib', 'meam')
        os.chdir(meam_dir)
        if self.toolchain.comp_family() in [toolchain.GCC]:
            meam_suffix = 'gfortran'
        elif self.toolchain.comp_family() in [toolchain.INTELCOMP]:
            meam_suffix = 'ifort'
        else:
            raise EasyBuildError("Don't know how to compile meam with compiler {0}".format(self.toolchain.comp_family()))

        cmd = "{0} make -f Makefile.{1} {2}".format(self.cfg['prebuildopts'], meam_suffix, self.cfg['buildopts'])
        (meam_output, _) = run_cmd(cmd, path=path, log_all=True, simple=False, log_output=verbose)

        # Tweak the resulting Makefile.lammps
        if self.toolchain.comp_family() in [toolchain.INTELCOMP]:
            apply_regex_substitutions('Makefile.lammps', [
                ('^(meam_SYSLIB\s*=.*)\s+lompstub\s+(.*)$', '\1 \2'),
                ('^(meam_SYSPATH\s*=\s*-L).*$', '\1%s' % os.environ['EBROOTIFORT'])
            ])

        return meam_output


    def build_step(self, verbose=False, path=None):
        """
        Start the actual build
        - typical: make -j X
        """

        out = None

        src_dir = self.cfg['start_dir']

        # Build meam if requested
        if self.cfg['use_meam']:
            out += self.build_meam()
        
        # Go back to the main directory
        os.chdir(src_dir)

        # See https://github.com/UoA-eResearch/easierbuild/blob/master/LAMMPS/build_lammps.txt
        # for further instructions, etc.
        return out

    def test_step(self):
        """
        Test the compilation
        - default: None
        """

        if self.cfg['runtest']:
            cmd = "make %s" % (self.cfg['runtest'])
            (out, _) = run_cmd(cmd, log_all=True, simple=False)

            return out

    def install_step(self):
        """
        Create the installation in correct location
        - typical: make install
        """

        cmd = "%s make install %s" % (self.cfg['preinstallopts'], self.cfg['installopts'])

        (out, _) = run_cmd(cmd, log_all=True, simple=False)

        return out
