##
# Copyright 2020-2021 Ghent University
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
"""
import os
from easybuild.tools.filetools import write_file
from easybuild.easyblocks.generic.binary import Binary
from easybuild.tools.modules import get_software_root
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.run import run_cmd


# this command is improvement (no hardcoded ways) of
# https://github.com/pinetree1/crispr-dav/blob/master/Examples/example1/run.sh
CUSTOM_SANITY_CHECK_COMMAND = r"""
{crisprdav_installdir}/crispr.pl --conf {crisprdav_installdir}/Examples/example1/conf.txt \
--region {crisprdav_installdir}/Examples/example1/amplicon.bed \
--crispr {crisprdav_installdir}/Examples/example1/site.bed \
--sitemap {crisprdav_installdir}/Examples/example1/sample.site \
--fastqmap {crisprdav_installdir}/Examples/example1/fastq.list \
--genome genomex  2>&1 | grep 'Generated HTML report for GENEX_CR1'
"""


class EB_CRISPR_minus_DAV(Binary):
    """
    Support for building/installing crispr-dav.
    """
    extract_sources = True

    def __init__(self, *args, **kwargs):
        super(EB_CRISPR_minus_DAV, self).__init__(*args, **kwargs)
        self.cfg['extract_sources'] = True

    def post_install_step(self):
        """Update config.txt files"""
        # getting paths of deps + files we will work with
        crisprdav_ex = os.path.join(self.installdir, 'Examples', 'example1')
        config_file = os.path.join(self.installdir, 'conf.txt')
        config_file_ex = os.path.join(crisprdav_ex, 'conf.txt')
        abra2_dir = get_software_root('ABRA2')
        prinseq_dir = get_software_root('PRINSEQ')
        flash_dir = get_software_root('FLASH')
        dep_err_msg = "Failed to find root directory for {sw_name}. Is it included as dependency?"
        if not abra2_dir:
            raise EasyBuildError(dep_err_msg.format(sw_name="ABRA2"))
        if not prinseq_dir:
            raise EasyBuildError(dep_err_msg.format(sw_name="PRINSEQ"))
        if not flash_dir:
            raise EasyBuildError(dep_err_msg.format(sw_name="FLASH"))
        # we will be changing both Examples/... conf file (for sanity checks) as well as root (for proper functioning)
        config_files_to_change = [config_file, config_file_ex]

        # create a backup of original Examples/example1/conf.txt file + the root conf.txt file
        run_cmd("cp {config_file_ex} {config_file_ex}_EB_BACKUP".format(config_file_ex=config_file_ex))
        run_cmd("cp {config_file} {config_file}_EB_BACKUP".format(config_file=config_file))

        # according to docs, we have to setup conf.txt so that it contains correct paths to dependencies
        # https://github.com/pinetree1/crispr-dav/blob/master/Install-and-Run.md
        # User then has to change conf.txt to include paths to genomes
        # changing both example conf.txt as well as the main one (in root directory) to make it easier for user.

        # func to replace everything in both conf.txt files
        self.modify_conf_files(crisprdav_ex, abra2_dir, prinseq_dir, flash_dir, config_files_to_change)

        # generating fastq file with correct paths (used for sanity checks)
        example_fastq_list_file = os.path.join(self.installdir, 'Examples', 'example1', 'fastq.list')
        fastq_list_file_text_formatted = ''
        for x in range(1, 5):
            # we have to use \t or it wont work!
            fastq_list_file_text = """sample{x}\t{crisprdav_ex}/rawfastq/sample{x}_R1.fastq.gz\t"""
            fastq_list_file_text += """{crisprdav_ex}/rawfastq/sample{x}_R2.fastq.gz"""
            if x < 4:
                fastq_list_file_text += '\n'  # formatting is very important here - last line cant be \n
            fastq_list_file_text_formatted += fastq_list_file_text.format(x=x, crisprdav_ex=crisprdav_ex)
        write_file(example_fastq_list_file, fastq_list_file_text_formatted)

    def sanity_check_step(self):
        """Custom sanity check paths for CRISPR-DAV"""
        crisprdav_installdir = self.installdir
        custom_paths = {
            'files': [],
            'dirs': ['Modules', 'Examples', 'Rscripts'],
        }

        # example command from docs - https://github.com/pinetree1/crispr-dav/blob/master/Install-and-Run.md
        custom_sanity_check_command_formatted = CUSTOM_SANITY_CHECK_COMMAND.format(
            crisprdav_installdir=crisprdav_installdir)
        custom_commands = [("crispr.pl --help 2>&1 | grep 'Usage: '", ''),
                           (custom_sanity_check_command_formatted, '')]

        super(EB_CRISPR_minus_DAV, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)

    def make_module_extra(self):
        txt = super(EB_CRISPR_minus_DAV, self).make_module_extra()
        txt += self.module_generator.prepend_paths('PATH', [''])
        return txt

    # replacing hardcoded paths in conf.txt files
    def modify_conf_files(self, crisprdav_ex, abra2_dir, prinseq_dir, flash_dir, config_files_to_change):
        # read input file
        for curr_config_file in config_files_to_change:
            fin = open(curr_config_file, "rt")
            # read file contents to string
            data = fin.read()
            # creating pairs (tuples) with original and new string
            ref_fasta_o = 'ref_fasta = genome/genomex.fa'
            ref_fasta_r = 'ref_fasta = {crisprdav_ex}/genome/genomex.fa'.format(crisprdav_ex=crisprdav_ex)
            bwa_idx_o = 'bwa_idx = genome/genomex.fa'
            bwa_idx_r = 'bwa_idx = {crisprdav_ex}/genome/genomex.fa'.format(crisprdav_ex=crisprdav_ex)
            refGene_o = 'refGene = genome/refgenex.txt'
            refGene_r = 'refGene = {crisprdav_ex}/genome/refgenex.txt'.format(crisprdav_ex=crisprdav_ex)
            abra_o = 'abra = /bfx/app/bin/abra-0.97-SNAPSHOT-jar-with-dependencies.jar'
            abra_r = 'abra = {abra2_dir}/abra2-2.23.jar'.format(abra2_dir=abra2_dir)
            prinseq_o = 'prinseq = /bfx/app/bin/prinseq-lite.pl'
            prinseq_r = 'prinseq = {prinseq_dir}/prinseq-lite.pl'.format(prinseq_dir=prinseq_dir)
            samtools_o = 'samtools = /bfx/app/bin/samtools'
            samtools_r = ''
            flash_o = 'flash = /bfx/app/bin/flash2'
            flash_r = 'flash = {flash_dir}/bin/flash2'.format(flash_dir=flash_dir)
            bedtools_o = 'bedtools = /bfx/app/bin/bedtools'
            bedtools_r = ''
            java_o = 'java = /usr/bin/java'
            java_r = ''
            pysamstats_o = 'pysamstats = /bfx/app/bin/pysamstats'
            pysamstats_r = ''
            rscript_o = 'rscript = /bfx/app/bin/Rscript'
            rscript_r = ''
            # saving in list of tuples for easy iteration
            text_to_replace = [
                (ref_fasta_o, ref_fasta_r),
                (bwa_idx_o, bwa_idx_r),
                (refGene_o, refGene_r),
                (abra_o, abra_r),
                (prinseq_o, prinseq_r),
                (samtools_o, samtools_r),
                (flash_o, flash_r),
                (bedtools_o, bedtools_r),
                (java_o, java_r),
                (pysamstats_o, pysamstats_r),
                (rscript_o, rscript_r)]

            # iterating through all tuples & replacing in string stored in memory
            for searched_str, replace_str in text_to_replace:
                data = data.replace(searched_str, replace_str)
            fin.close()
            # override the original conf.txt file with modified conf.txt string stored in memory
            fin = open(curr_config_file, "wt")
            fin.write(data)
            fin.close()
