##
# This file is an EasyBuild reciPY as per https://github.com/easybuilders/easybuild
#
# Copyright:: Copyright 2012-2024 Uni.Lu/LCSB, NTUA
# Authors::   Cedric Laczny <cedric.laczny@uni.lu>, Fotis Georgatos <fotis@cern.ch>, Kenneth Hoste
# License::   MIT/GPL
# $Id$
#
# This work implements a part of the HPCBIOS project and is a component of the policy:
# http://hpcbios.readthedocs.org/en/latest/HPCBIOS_2012-94.html
#
# Updated for SAMTools 1.14
# J. Sassmannshausen (GSTT)
##
"""
EasyBuild support for building SAMtools (SAM - Sequence Alignment/Map), implemented as an easyblock

@author: Cedric Laczny (Uni.Lu)
@author: Fotis Georgatos (Uni.Lu)
@author: Kenneth Hoste (Ghent University)
"""
from easybuild.tools import LooseVersion
import glob
import os
import stat

from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import adjust_permissions, copy_dir, copy_file


class EB_SAMtools(ConfigureMake):
    """
    Support for building SAMtools; SAM (Sequence Alignment/Map) format
    is a generic format for storing large nucleotide sequence alignments.
    """

    def __init__(self, *args, **kwargs):
        """Define lists of files to install."""
        super(EB_SAMtools, self).__init__(*args, **kwargs)

        self.bin_files = ["misc/blast2sam.pl",
                          "misc/bowtie2sam.pl", "misc/export2sam.pl", "misc/interpolate_sam.pl",
                          "misc/novo2sam.pl", "misc/psl2sam.pl", "misc/sam2vcf.pl", "misc/samtools.pl",
                          "misc/soap2sam.pl", "misc/wgsim_eval.pl",
                          "misc/zoom2sam.pl", "misc/md5sum-lite", "misc/md5fa", "misc/maq2sam-short",
                          "misc/maq2sam-long", "misc/wgsim", "samtools"]

        self.lib_files = []

        self.include_files = ["bam.h", "bam2bcf.h", "sample.h"]
        self.include_dirs = []

        if LooseVersion(self.version) == LooseVersion('0.1.18'):
            # seqtk is no longer there in v0.1.19 and seqtk is not in 0.1.17
            self.bin_files += ["misc/seqtk"]
        elif LooseVersion(self.version) >= LooseVersion('0.1.19'):
            # new tools in v0.1.19
            self.bin_files += ["misc/ace2sam", "misc/r2plot.lua",
                               "misc/vcfutils.lua"]

        if LooseVersion(self.version) >= LooseVersion('0.1.19') and LooseVersion(self.version) < LooseVersion('1.0'):
            self.bin_files += ["misc/bamcheck", "misc/plot-bamcheck"]

        if LooseVersion(self.version) < LooseVersion('1.0'):
            self.bin_files += ["bcftools/vcfutils.pl", "bcftools/bcftools"]
            self.include_files += ["bgzf.h", "faidx.h", "khash.h", "klist.h", "knetfile.h", "razf.h",
                                   "kseq.h", "ksort.h", "kstring.h"]
        elif LooseVersion(self.version) >= LooseVersion('1.0'):
            self.bin_files += ["misc/plot-bamstats", "misc/seq_cache_populate.pl"]

        if LooseVersion(self.version) < LooseVersion('1.2'):
            # kaln aligner removed in 1.2 (commit 19c9f6)
            self.include_files += ["kaln.h"]

        if LooseVersion(self.version) < LooseVersion('1.4'):
            # errmod.h and kprobaln.h removed from 1.4
            self.include_files += ["errmod.h", "kprobaln.h"]

        if LooseVersion(self.version) < LooseVersion('1.10'):
            self.include_files += ["sam_header.h"]
            self.bin_files += ["misc/varfilter.py"]

        if LooseVersion(self.version) < LooseVersion('1.14'):
            # bam_endian.h and sam.h removed from 1.14
            self.include_files += ["bam_endian.h", "sam.h"]
            self.lib_files = ["libbam.a"]

    def configure_step(self):
        """Ensure correct compiler command & flags are used via arguments to 'make' build command"""
        for var in ['CC', 'CXX', 'CFLAGS', 'CXXFLAGS']:
            if var in os.environ:
                self.cfg.update('buildopts', '%s="%s"' % (var, os.getenv(var)))

        # configuring with --prefix only supported with v1.3 and more recent
        if LooseVersion(self.version) >= LooseVersion('1.3'):
            super(EB_SAMtools, self).configure_step()

    def install_step(self):
        """
        Install by copying files to install dir
        """

        # also install libhts.a & corresponding header files, if it's there
        # may not always be there, for example for older versions, or when HTSlib is included as a dep
        htslibs = glob.glob(os.path.join('htslib-*/libhts.a'))
        if htslibs:
            if len(htslibs) == 1:
                htslib = htslibs[0]

                self.log.info("Found %s, so also installing it", htslib)
                self.lib_files.append(htslib)

                # if the library is there, we also expect the header files to be there
                hts_inc_dir = os.path.join(os.path.dirname(htslib), 'htslib')
                if os.path.exists(hts_inc_dir):
                    self.include_dirs.append(hts_inc_dir)
                else:
                    raise EasyBuildError("%s not found, don't know how to install header files for %s",
                                         hts_inc_dir, htslib)
            else:
                raise EasyBuildError("Found multiple hits for libhts.a, don't know which one to copy: %s", htslibs)
        else:
            self.log.info("No libhts.a found, so not installing it")

        install_files = [
            ('include/bam', self.include_files),
            ('lib', self.lib_files),
        ]
        install_dirs = [
            ('include', self.include_dirs),
        ]

        # v1.3 and more recent supports 'make install', but this only installs (some of) the binaries...
        if LooseVersion(self.version) >= LooseVersion('1.3'):
            super(EB_SAMtools, self).install_step()

            # figure out which bin files are missing, and try copying them
            missing_bin_files = []
            for binfile in self.bin_files:
                if not os.path.exists(os.path.join(self.installdir, 'bin', os.path.basename(binfile))):
                    missing_bin_files.append(binfile)
            install_files.append(('bin', missing_bin_files))

        else:
            # copy binaries manually for older versions
            install_files.append(('bin', self.bin_files))

        self.log.debug("Installing files by copying them 'manually': %s", install_files)
        for (destdir, files) in install_files:
            for fn in files:
                dest = os.path.join(self.installdir, destdir, os.path.basename(fn))
                copy_file(os.path.join(self.cfg['start_dir'], fn), dest)

        self.log.info("Installing directory by copying them 'manually': %s", install_dirs)
        for (destdir, dirnames) in install_dirs:
            for dirname in dirnames:
                dest = os.path.join(self.installdir, destdir, os.path.basename(dirname))
                copy_dir(os.path.join(self.cfg['start_dir'], dirname), dest)

        # enable r-x permissions for group/others
        perms = stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH
        adjust_permissions(self.installdir, perms, add=True, recursive=True)

    def sanity_check_step(self):
        """Custom sanity check for SAMtools."""

        bins = [os.path.join('bin', os.path.basename(f)) for f in self.bin_files]
        incs = [os.path.join('include', 'bam', os.path.basename(f)) for f in self.include_files]
        libs = [os.path.join('lib', os.path.basename(f)) for f in self.lib_files]

        custom_paths = {
            'files': bins + incs + libs,
            'dirs': [os.path.join('include', os.path.basename(d)) for d in self.include_dirs],
        }
        super(EB_SAMtools, self).sanity_check_step(custom_paths=custom_paths)
