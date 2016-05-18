##
# Copyright 2009-2016 Ghent University
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://vscentrum.be/nl/en),
# Flemish Research Foundation (FWO) (http://www.fwo.be/en)
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
EasyBuild support for Siesta, implemented as an easyblock

@author: Miguel Dias Costa (National university of Singapore)
"""

import os
import easybuild.tools.toolchain as toolchain
from easybuild.framework.easyconfig import CUSTOM
from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.easyblocks.generic.makecp import MakeCp


class EB_Siesta(MakeCp):
    """Support for building and installing Siesta."""

    @staticmethod
    def extra_options(extra_vars=None):
        """
        Define list of files or directories to be copied after make
        """
        extra = {
            'files_to_copy': [[], "List of files or dirs to copy", CUSTOM],
            'with_transiesta': [True, "Build transiesta", CUSTOM],
            'with_utils': [True, "Build all utils", CUSTOM],
        }
        if extra_vars is None:
            extra_vars = {}
        extra.update(extra_vars)
        return ConfigureMake.extra_options(extra_vars=extra)

    def build_step(self):
        """Custom build procedure for Siesta."""
        cfg_cmd = '../Src/obj_setup.sh && ../Src/configure'

        if self.toolchain.options.get('usempi', None):
            cfg_cmd += ' --enable-mpi '

        self.cfg.update('prebuildopts', 'cd Obj && ' + cfg_cmd + ' && ')

        build_vars = 'COMP_LIBS="" '
        build_vars += 'BLAS_LIBS="' + os.environ['LIBBLAS'] + '" '
        build_vars += 'LAPACK_LIBS="' + os.environ['LIBLAPACK'] + '" '
        build_vars += 'BLACS_LIBS="' + os.environ['LIBBLACS'] + '" '
        build_vars += 'SCALAPACK_LIBS="' + os.environ['LIBSCALAPACK'] + '"'

        self.cfg.update('buildopts', build_vars)

        if self.cfg['with_transiesta']:
            self.cfg.update('buildopts', ' && cd .. && mkdir Obj2 && cd Obj2 && ')
            self.cfg.update('buildopts', cfg_cmd + ' && make transiesta ' + build_vars)

        if self.cfg['with_utils']:
            self.cfg.update('buildopts', ' && cd ../Util && sh ./build_all.sh')

        super(EB_Siesta, self).build_step()

    def install_step(self):
        """Custom install procedure for Siesta."""

        bins = ['Obj/siesta']

        if self.cfg['with_transiesta']:
            bins.extend(['Obj2/transiesta'])

        if self.cfg['with_utils']:
            utils = [os.path.join('Bands', b) for b in ['eigfat2plot', 'new.gnubands']]
            utils.append(os.path.join('CMLComp', 'ccViz'))
            utils.extend(os.path.join('COOP', b) for b in ['dm_creator', 'fat', 'mprop'])
            utils.extend(os.path.join('Contrib/APostnikov', b) for b in ['eig2bxsf', 'fmpdos', 'md2axsf',
                                                                         'rho2xsf', 'vib2xsf', 'xv2xsf'])
            utils.extend(os.path.join('Denchar', b) for b in ['Examples/2dplot.py', 'Examples/surf.py', 'Src/denchar'])
            utils.extend(os.path.join('DensityMatrix', b) for b in ['cdf2dm', 'dm2cdf'])
            utils.append(os.path.join('Eig2DOS', 'Eig2DOS'))
            utils.extend(os.path.join('Gen-basis', b) for b in ['gen-basis', 'ioncat', 'ionplot.sh'])
            utils.extend(os.path.join('Grid', b) for b in ['cdf2grid', 'cdf2xsf', 'grid2cdf', 'grid2cube', 'grid2val'])
            utils.extend(os.path.join('HSX', b) for b in ['hs2hsx', 'hsx2hs'])
            utils.append(os.path.join('Helpers', 'get_chem_labels'))
            utils.append(os.path.join('MPI_test', 'pi3'))
            utils.append(os.path.join('Macroave', 'Src/macroave'))
            utils.append(os.path.join('ON', 'lwf2cdf'))
            utils.extend(os.path.join('Optimizer', b) for b in ['simplex', 'swarm'])
            utils.append(os.path.join('Projections', 'orbmol_proj'))
            utils.append(os.path.join('STM', 'simple-stm/plstm'))
            utils.extend(os.path.join('SiestaSubroutine/FmixMD/Src', b) for b in ['driver', 'para', 'simple'])
            utils.append(os.path.join('TBTrans', 'tbtrans'))
            utils.extend(os.path.join('VCA', b) for b in ['fractional', 'mixps'])
            utils.extend(os.path.join('Vibra/Src', b) for b in ['fcbuild', 'vibrator'])
            utils.extend(os.path.join('WFS', b) for b in ['info_wfsx', 'readwf', 'readwfx', 'wfs2wfsx', 'wfsnc2wfsx',
                                                          'wfsx2wfs'])
            utils.append(os.path.join('pdosxml', 'pdosxml'))
            utils.append(os.path.join('pseudo-xml', 'xml2psf'))
            utils.append(os.path.join('test-xml', 'test-xml'))

            bins.extend([os.path.join('Util', u) for u in utils])

        self.cfg['files_to_copy'] = [(bins, 'bin')]

        super(EB_Siesta, self).install_step()

    def sanity_check_step(self):
        """Custom sanity check for Siesta."""

        bins = ['bin/siesta']

        if self.cfg['with_transiesta']:
            bins.extend(['bin/transiesta'])

        if self.cfg['with_utils']:
            bins.extend([os.path.join('bin', util) for util in '2dplot.py', 'Eig2DOS', 'ccViz', 'cdf2dm', 'cdf2grid',
                         'cdf2xsf', 'denchar', 'dm2cdf', 'dm_creator', 'driver', 'eig2bxsf', 'eigfat2plot', 'fat',
                         'fcbuild', 'fmpdos', 'fractional', 'gen-basis', 'get_chem_labels', 'grid2cdf',
                         'grid2cube', 'grid2val', 'hs2hsx', 'hsx2hs', 'info_wfsx', 'ioncat', 'ionplot.sh', 'lwf2cdf',
                         'macroave', 'md2axsf', 'mixps', 'mprop', 'new.gnubands', 'orbmol_proj', 'para', 'pdosxml',
                         'pi3', 'plstm', 'readwf', 'readwfx', 'rho2xsf', 'simple', 'simplex', 'surf.py', 'swarm',
                         'tbtrans', 'test-xml', 'vib2xsf', 'vibrator', 'wfs2wfsx', 'wfsnc2wfsx', 'wfsx2wfs', 'xml2psf',
                         'xv2xsf'])

        custom_paths = {
            'files': bins,
            'dirs': []
        }

        super(EB_Siesta, self).sanity_check_step(custom_paths=custom_paths)
