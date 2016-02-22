##
# Copyright 2009-2014 Ghent University
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
EasyBuild support for building and installing QIIME, implemented as an easyblock

@author: Stijn De Weirdt (Ghent University)
@author: Dries Verdegem (Ghent University)
@author: Kenneth Hoste (Ghent University)
@author: Pieter De Baets (Ghent University)
@author: Jens Timmerman (Ghent University)
"""
import os
import re
import tempfile

import easybuild.tools.environment as env
from easybuild.easyblocks.generic.pythonpackage import PythonPackage, det_pylibdir
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.modules import get_software_root
from easybuild.tools.run import run_cmd


class EB_QIIME(PythonPackage):
    """Support for building/installing QIIME."""

    def test_step(self):
        """Run tests provided by QIIME."""
        # run included tests, unless instructed otherwise
        if not self.cfg['runtest'] or isinstance(self.cfg['runtest'], bool):
            self.cfg['runtest'] = "cd tests && python all_tests.py"
            self.log.info("No tests defined, so running '%s' for testing QIIME", self.cfg['runtest'])

        # create QIIME config file for tests
        tmpdir = tempfile.mkdtemp()
        bindir = os.path.join(tmpdir, 'bin')
        ggdir = os.path.join(self.builddir, 'gg_13_5_otus')
        qiime_cfg_file = os.path.join(self.builddir, "qiime.cfg")
        env.setvar('QIIME_CONFIG_FP', qiime_cfg_file)
        txt = '\n'.join([
            "qiime_scripts_dir  %s" % bindir,
            "cluster_jobs_fp  %s" % os.path.join(bindir, 'start_parallel_jobs.py'),
            "pynast_template_alignment_fp %s" % os.path.join(self.cfg['start_dir'], 'core_set_aligned.fasta.imputed'),
            "template_alignment_lanemask_fp %s" % os.path.join(self.cfg['start_dir'], 'lanemask_in_1s_and_0s'),
            "assign_taxonomy_reference_seqs_fp %s" % os.path.join(ggdir, 'rep_set', '97_otus.fasta'),
            "assign_taxonomy_id_to_taxonomy_fp %s" % os.path.join(ggdir, 'taxonomy', '97_otu_taxonomy.txt'),
            "temp_dir %s" % tmpdir,
        ])
        try:
            f = open(qiime_cfg_file, 'w')
            f.write(txt)
            f.close()
            self.log.debug("Successfully created test QIIME config file %s", qiime_cfg_file)
        except IOError, err:
            raise EasyBuildError("Failed to create QIIME config file %s for tests: %s", qiime_cfg_file, err)

        # install QIIME to tmpdir for testing
        pylibdir = os.path.join(tmpdir, det_pylibdir())
        cmd = "python setup.py install --prefix=%s" % tmpdir
        cmd += self.cfg['installopts']
        run_cmd(cmd, log_all=True, simple=True)

        # set required env vars
        env.setvar('BLASTMAT', os.path.join(get_software_root('BLAST'), 'data'))
        # see http://qiime.org/install/install.html#ampliconnoise-install-notes
        an_data = os.path.join(get_software_root('AmpliconNoise'), 'Data')
        env.setvar('PYRO_LOOKUP_FILE', os.path.join(an_data, 'LookUp_E123.dat'))
        env.setvar('SEQ_LOOKUP_FILE', os.path.join(an_data, 'Tran.dat'))

        # add temporary install location to $PATH and $PYTHONPATH
        cmd_setup = "export PATH=%s:$PATH && export PYTHONPATH=%s:$PYTHONPATH" % (bindir, pylibdir)
        # unset $TMPDIR and co to avoid broken assign_taxonomy tests,
        # see https://groups.google.com/forum/#!msg/qiime-forum/twJKKL3LcnA/Tb_sVeS7leQJ)
        cmd_setup += " && unset TMPDIR && unset TEMP && unset TMP"

        # print QIIME config for debugging purposes
        cmd = "%s && %s" % (cmd_setup, 'print_qiime_config.py -t')
        (out, ec) = run_cmd(cmd, simple=False, log_all=False, log_ok=False, log_output=True)
        ok_regex = re.compile("^OK$", re.M)
        if not ok_regex.search(out):
            raise EasyBuildError("Output of '%s' indicates unresolved problems: %s", cmd, out)

        # run actual tests, prepend PATH/PYTHONPATH manipulation to test command
        cmd = "%s && %s" % (cmd_setup, self.cfg['runtest'])
        # allow failing tests for now
        #(out, ec) = run_cmd(cmd, simple=False, log_all=False, log_ok=False, log_output=True)
        #self.log.debug("Output of %s (exit code %s): %s", cmd, ec, out)
        run_cmd(cmd, log_all=True, simple=True)

    def make_module_extra(self):
        """Add QIIME-specific commands to module file, e.g. setting of $QIIME_CONFIG."""
        txt = super(EB_QIIME, self).make_module_extra()

        qiime_cfg_fn = "qiime_config"
        qiime_cfg = os.path.join(self.installdir, qiime_cfg_fn)
        qiime_cfg_txt = "qiime_scripts_dir %s" % os.path.join(self.installdir, 'bin')
        try:
            f = open(qiime_cfg, 'w')
            f.write(qiime_cfg_txt)
            f.close()
            self.log.debug("Successfully created QIIME config file at: %s", qiime_cfg)
        except IOError, err:
            raise EasyBuildError("Failed to create QIIME config file at: %s (%s)", qiime_cfg, err)

        txt += self.moduleGenerator.prepend_paths('QIIME_CONFIG_FP', [qiime_cfg_fn])

        blast = get_software_root('BLAST')
        txt += self.moduleGenerator.set_environment('BLASTMAT', os.path.join(blast, 'data'))
        an_data = os.path.join(get_software_root('AmpliconNoise'), 'Data')
        txt += self.moduleGenerator.set_environment('PYRO_LOOKUP_FILE', os.path.join(an_data, 'LookUp_E123.dat'))
        txt += self.moduleGenerator.set_environment('SEQ_LOOKUP_FILE', os.path.join(an_data, 'Tran.dat'))
        return txt

