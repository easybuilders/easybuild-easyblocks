##
# Copyright 2020-2025 Ghent University
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
EasyBuild support for building and installing CRISPR-DAV, implemented as an easyblock.

@author: Denis Kristak (INUITS)
@author: Kenneth Hoste (HPC-UGent)
"""
import glob
import os
from easybuild.easyblocks.generic.binary import Binary
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import apply_regex_substitutions, back_up_file, write_file
from easybuild.tools.modules import get_software_root


class EB_CRISPR_minus_DAV(Binary):
    """
    Support for building/installing CRISPR-DAV.
    """

    def __init__(self, *args, **kwargs):
        """Constructor for CRISPR-DAV easyblock."""
        super(EB_CRISPR_minus_DAV, self).__init__(*args, **kwargs)
        self.cfg['extract_sources'] = True

    def post_processing_step(self):
        """Update configuration files with correct paths to dependencies and files in installation."""

        # getting paths of deps + files we will work with
        example_dir = os.path.join(self.installdir, 'Examples')
        config_file = os.path.join(self.installdir, 'conf.txt')

        dep_roots = {}
        for dep in ('ABRA2', 'BEDTools', 'FLASH', 'Java', 'PRINSEQ', 'pysamstats', 'R', 'SAMtools'):
            root = get_software_root(dep)
            if root:
                dep_roots[dep] = root
            else:
                raise EasyBuildError("Failed to find root directory for %s. Is it included as dependency?", dep)

        # we will be changing both Examples/... conf file (for sanity checks) as well as root (for proper functioning)
        cfg_files = [config_file] + glob.glob(os.path.join(example_dir, 'example*', 'conf.txt'))

        # create a backup of original Examples/example1/conf.txt file + the root conf.txt file
        for filename in cfg_files:
            back_up_file(filename)

        # according to docs, we have to setup conf.txt so that it contains correct paths to dependencies
        # https://github.com/pinetree1/crispr-dav/blob/master/Install-and-Run.md
        # User then has to change conf.txt to include paths to genomes
        # changing both example conf.txt as well as the main one (in root directory) to make it easier for user.

        # func to replace everything in both conf.txt files
        self.modify_conf_files(dep_roots, cfg_files)

        # generating fastq file with correct paths (used for sanity checks)
        for example in ('example1', 'example2'):
            example_dir = os.path.join(example_dir, example)
            fastq_list_file = os.path.join(example_dir, 'fastq.list')
            fastq_list = []
            rawfastq_dir = os.path.join(example_dir, 'rawfastq')

            for x in range(1, 5):
                # we have to use \t or it wont work!
                line = '\t'.join([
                    'sample%s' % x,
                    os.path.join(rawfastq_dir, 'sample%s_R1.fastq.gz' % x),
                    os.path.join(rawfastq_dir, 'sample%s_R2.fastq.gz' % x),
                ])
                fastq_list.append(line)

            # last line should not end with newline (\n)!
            write_file(fastq_list_file, '\n'.join(fastq_list))

    def sanity_check_step(self):
        """Custom sanity check paths for CRISPR-DAV"""
        custom_paths = {
            'files': ['crispr.pl'],
            'dirs': ['Modules', 'Examples', 'Rscripts'],
        }

        # example command from docs - https://github.com/pinetree1/crispr-dav/blob/master/Install-and-Run.md
        # this command is an improvement (no hardcoded stuff) of
        # https://github.com/pinetree1/crispr-dav/blob/master/Examples/example1/run.sh
        example_dir = os.path.join(self.installdir, 'Examples', 'example1')
        outfile = os.path.join(self.builddir, 'test.out')
        example_cmd = ' '.join([
            os.path.join(self.installdir, 'crispr.pl'),
            "--conf %s" % os.path.join(example_dir, 'conf.txt'),
            "--region %s" % os.path.join(example_dir, 'amplicon.bed'),
            "--crispr %s" % os.path.join(example_dir, 'site.bed'),
            "--sitemap %s" % os.path.join(example_dir, 'sample.site'),
            "--fastqmap %s" % os.path.join(example_dir, 'fastq.list'),
            "--conf %s" % os.path.join(example_dir, 'conf.txt'),
            "--genome genomex",
            "2>&1 | tee %s" % outfile,
            " && grep 'Generated HTML report for GENEX_CR1' %s" % outfile,
        ])

        custom_commands = [
            "crispr.pl --help 2>&1 | grep 'Usage: '",
            example_cmd,
        ]

        super(EB_CRISPR_minus_DAV, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)

    def make_module_extra(self):
        txt = super(EB_CRISPR_minus_DAV, self).make_module_extra()
        txt += self.module_generator.prepend_paths('PATH', [''])
        return txt

    def modify_conf_files(self, dep_roots, cfg_files):
        """Replace hardcoded paths in config files."""

        abra2_jar = os.path.join(dep_roots['ABRA2'], 'abra2-%s.jar' % os.getenv('EBVERSIONABRA2'))
        pysamstats_bin = os.path.join(dep_roots['pysamstats'], 'bin', 'pysamstats')

        regex_subs = [
            (r'^abra\s*=.*/abra.*.jar', 'abra = ' + abra2_jar),
            (r'^bedtools\s*=.*/bin/bedtools', 'bedtools = ' + os.path.join(dep_roots['BEDTools'], 'bin', 'bedtools')),
            (r'^flash\s*=.*/bin/flash2', 'flash = ' + os.path.join(dep_roots['FLASH'], 'bin', 'flash2')),
            (r'^java\s*=.*/bin/java', 'java = ' + os.path.join(dep_roots['Java'], 'bin', 'java')),
            (r'^prinseq\s*=.*/prinseq-lite.pl', 'prinseq = ' + os.path.join(dep_roots['PRINSEQ'], 'prinseq-lite.pl')),
            (r'^pysamstats\s*=.*/bin/pysamstats', 'pysamstats = ' + pysamstats_bin),
            (r'^rscript\s*=.*/bin/Rscript', 'rscript = ' + os.path.join(dep_roots['R'], 'bin', 'Rscript')),
            (r'^samtools\s*=.*/bin/samtools', 'samtools = ' + os.path.join(dep_roots['SAMtools'], 'bin', 'samtools')),
        ]

        for cfg_file in cfg_files:
            dirname = os.path.dirname(cfg_file)
            if os.path.basename(dirname).startswith('example'):
                example_dir = dirname
            else:
                example_dir = os.path.join(self.installdir, 'Examples', 'example1')

            genome_dir = os.path.join(example_dir, 'genome')
            genomex_fa = os.path.join(genome_dir, 'genomex.fa')

            regex_subs.extend([
                (r'^ref_fasta\s*=.*genome/genomex.fa', 'ref_fasta = ' + genomex_fa),
                (r'^bwa_idx\s*=.*genome/genomex.fa', 'bwa_idx = ' + genomex_fa),
                (r'^refGene\s*=.*genome/refgenex.txt', 'refGene = ' + os.path.join(genome_dir, 'refgenex.txt')),
            ])

            apply_regex_substitutions(cfg_file, regex_subs, on_missing_match='error')
