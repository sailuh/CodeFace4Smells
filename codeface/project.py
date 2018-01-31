# This file is part of Codeface. Codeface is free software: you can
# redistribute it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, version 2.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
#
# Copyright 2013 by Siemens AG
# All Rights Reserved.

from logging import getLogger; log = getLogger(__name__)
from progressbar import ProgressBar, Percentage, Bar
from pkg_resources import resource_filename
from os.path import join as pathjoin, split as pathsplit, abspath, exists as pathexists
from os import makedirs, error as os_error

from .dbmanager import DBManager
from .configuration import Configuration, ConfigurationError
from .cluster.cluster import doProjectAnalysis, LinkType
from .ts import dispatch_ts_analysis
from .util import (execute_command, generate_reports, layout_graph,
                   check4ctags, check4cppstats, BatchJobPool, generate_analysis_windows,
                   generate_report_st)
from .tech_smell import doTechSmellAnalysis

def loginfo(msg):
    ''' Pickleable function for multiprocessing '''
    log.info(msg)

def project_setup(conf, recreate):
    '''
    This method updates the project in the database with the release
    information given in the configuration.
    Returns the project ID, the database manager and the list of range ids
    for the ranges between the releases specified in the configuration.
    '''
    # Set up project in database and retrieve ranges to analyse
    log.info("=> Setting up project '{c[project]}'".format(c=conf))
    dbm = DBManager(conf)
    new_range_ids = dbm.update_release_timeline(conf["project"],
            conf["tagging"], conf["revisions"], conf["rcs"],
            recreate_project=recreate)
    project_id = dbm.getProjectID(conf["project"], conf["tagging"])
    revs = conf["revisions"]
    all_range_ids = [dbm.getReleaseRangeID(project_id,
            ( dbm.getRevisionID(project_id, start),
              dbm.getRevisionID(project_id, end)))
            for (start, end) in zip(revs, revs[1:])]
    return project_id, dbm, all_range_ids

def project_analyse(resdir, gitdir, codeface_conf, project_conf,
                    no_report, loglevel, logfile, recreate, profile_r,
                    n_jobs, tagging_type, reuse_db):
    pool = BatchJobPool(int(n_jobs))
    conf = Configuration.load(codeface_conf, project_conf)
    tagging = conf["tagging"]
    if tagging_type is not "default":

        if not tagging_type in LinkType.get_all_link_types():
            log.critical('Unsupported tagging mechanism specified!')
            raise ConfigurationError('Unsupported tagging mechanism.')
        # we override the configuration value
        if tagging is not tagging_type:
            log.warn(
                "tagging value is overwritten to {0} because of --tagging"
                .format(tagging_type))
            tagging = tagging_type
            conf["tagging"] = tagging

    project = conf["project"]
    repo = pathjoin(gitdir, conf["repo"], ".git")
    project_resdir = pathjoin(resdir, project, tagging)
    range_by_date = False
    
    ## if 3 months window analysis is specified generate the related
    ## configuration. At most 3 years are considered.
    if conf["revisions"] == "3months":
        window_size_months = 3 # Window size in months
        num_window = 12  # analyze last 3 years
        revs, rcs = generate_analysis_windows(repo, window_size_months, num_window)
        conf["revisions"] = revs
        conf["rcs"] = rcs
        range_by_date = True

    # When revisions are not provided by the configuration file
    # generate the analysis window automatically
    if len(conf["revisions"]) < 2:
        window_size_months = 3 # Window size in months
        num_window = -1  # Number of ranges to analyse, -1 captures all ranges
        revs, rcs = generate_analysis_windows(repo, window_size_months)
        conf["revisions"] = revs[-num_window-1:]
        conf["rcs"] = rcs[-num_window-1:]
        range_by_date = True

    # TODO: Sanity checks (ensure that git repo dir exists)
    if tagging == LinkType.proximity:
        check4ctags()
    elif tagging in (LinkType.feature, LinkType.feature_file):
        check4cppstats()

    project_id, dbm, all_range_ids = project_setup(conf, recreate)

    ## Save configuration file
    conf.write()
    project_conf = conf.get_conf_file_loc()

    # Analyse new revision ranges
    for i, range_id in enumerate(all_range_ids):
        start_rev, end_rev, rc_rev = dbm.get_release_range(project_id, range_id)
        range_resdir = pathjoin(project_resdir, "{0}-{1}".
                format(start_rev, end_rev))
        prefix = "  -> Revision range {0}..{1}: ".format(start_rev, end_rev)

        #######
        # STAGE 1: Commit analysis
        s1 = pool.add(
                doProjectAnalysis,
                (conf, start_rev, end_rev, rc_rev, range_resdir, repo,
                    reuse_db, True, range_by_date),
                startmsg=prefix + "Analysing commits...",
                endmsg=prefix + "Commit analysis done."
            )

        #########
        # STAGE 2: Cluster analysis
        exe = abspath(resource_filename(__name__, "R/cluster/persons.r"))
        cwd, _ = pathsplit(exe)
        cmd = []
        cmd.append(exe)
        cmd.extend(("--loglevel", loglevel))
        if logfile:
            cmd.extend(("--logfile", "{}.R.r{}".format(logfile, i)))
        cmd.extend(("-c", codeface_conf))
        cmd.extend(("-p", project_conf))
        cmd.append(range_resdir)
        cmd.append(str(range_id))

        s2 = pool.add(
                execute_command,
                (cmd,),
                {"direct_io":True, "cwd":cwd},
                deps=[s1],
                startmsg=prefix + "Detecting clusters...",
                endmsg=prefix + "Detecting clusters done."
            )

        #########
        # STAGE 3: Generate cluster graphs
        if not no_report:
            pool.add(
                    generate_reports,
                    (start_rev, end_rev, range_resdir),
                    deps=[s2],
                    startmsg=prefix + "Generating reports...",
                    endmsg=prefix + "Report generation done."
                )

    # Wait until all batch jobs are finished
    pool.join()

    #########
    # Global stage 1: Time series generation
    log.info("=> Preparing time series data")
    dispatch_ts_analysis(project_resdir, conf)

    #########
    # Global stage 2: Complexity analysis
    ## NOTE: We rely on proper timestamps, so we can only run
    ## after time series generation
    log.info("=> Performing complexity analysis")
    for i, range_id in enumerate(all_range_ids):
        log.info("  -> Analysing range {}".format(range_id))
        exe = abspath(resource_filename(__name__, "R/complexity.r"))
        cwd, _ = pathsplit(exe)
        cmd = [exe]
        if logfile:
            cmd.extend(("--logfile", "{}.R.complexity.{}".format(logfile, i)))
        cmd.extend(("--loglevel", loglevel))
        cmd.extend(("-c", codeface_conf))
        cmd.extend(("-p", project_conf))
        cmd.extend(("-j", str(n_jobs)))
        cmd.append(repo)
        cmd.append(str(range_id))
        execute_command(cmd, direct_io=True, cwd=cwd)

    #########
    # Global stage 3: Time series analysis
    log.info("=> Analysing time series")
    exe = abspath(resource_filename(__name__, "R/analyse_ts.r"))
    cwd, _ = pathsplit(exe)
    cmd = [exe]
    if profile_r:
        cmd.append("--profile")
    if logfile:
        cmd.extend(("--logfile", "{}.R.ts".format(logfile)))
    cmd.extend(("--loglevel", loglevel))
    cmd.extend(("-c", codeface_conf))
    cmd.extend(("-p", project_conf))
    cmd.extend(("-j", str(n_jobs)))
    cmd.append(project_resdir)
    execute_command(cmd, direct_io=True, cwd=cwd)
    log.info("=> Codeface run complete!")

def mailinglist_analyse(resdir, mldir, codeface_conf, project_conf, loglevel,
                        logfile, jobs, mailinglists, use_corpus):
    conf = Configuration.load(codeface_conf, project_conf)
    ml_resdir = pathjoin(resdir, conf["project"], "ml")

    exe = abspath(resource_filename(__name__, "R/ml/batch.r"))
    cwd, _ = pathsplit(exe)
    cmd = []
    cmd.extend(("--loglevel", loglevel))
    cmd.extend(("-c", codeface_conf))
    cmd.extend(("-p", project_conf))
    cmd.extend(("-j", str(jobs)))
    if (use_corpus):
        cmd.append("--use-corpus")
    cmd.append(ml_resdir)
    cmd.append(mldir)
    if not mailinglists:
        mailinglist_conf = conf["mailinglists"]
    else:
        mailinglist_conf = []
        for mln in mailinglists:
            match = [ml for ml in conf["mailinglists"] if ml["name"] == mln]
            if not match:
                log.fatal("Mailinglist '{}' not listed in configuration file!".
                    format(ml))
                raise Exception("Unknown mailing list")
            if len(match) > 1:
                log.fatal("Mailinglist '{}' specified twice in configuration file!".
                    format(ml))
                raise Exception("Invalid config file")
            mailinglist_conf.append(match[0])

    for i, ml in enumerate(mailinglist_conf):
        log.info("=> Analysing mailing list '{name}' of type '{type}'".
                format(**ml))
        logargs = []
        if logfile:
            logargs = ["--logfile", "{}.R.ml.{}".format(logfile, i)]
        execute_command([exe] + logargs + cmd + [ml["name"]],
                direct_io=True, cwd=cwd)
    log.info("=> Codeface mailing list analysis complete!")


def sociotechnical_analyse(resdir, codeface_conf, project_conf, loglevel,
                           logfile, n_jobs):
    conf = Configuration.load(codeface_conf, project_conf)
    project_resdir = pathjoin(resdir, conf["project"])

    exe = abspath(resource_filename(__name__, "R/sociotechnical.r"))
    cwd, _ = pathsplit(exe)
    cmd = [exe]
    if logfile:
        cmd.extend(("--logfile", "{}.R.sociotechnical".format(logfile)))
    cmd.extend(("--loglevel", loglevel))
    cmd.extend(("-c", codeface_conf))
    cmd.extend(("-p", project_conf))
    cmd.extend(("-j", str(n_jobs)))
    cmd.append(project_resdir)

    log.info("=> Performing socio-technical analysis")
    execute_command(cmd, direct_io=True, cwd=cwd)
    generate_report_st(pathjoin(resdir, conf["project"], "st"))
    log.info("=> Codeface socio-technical analysis complete!")

def techsmell_analyse(resdir, gitdir, tsadir, codeface_conf, project_conf,
                      loglevel, logfile, n_jobs):
    conf = Configuration.load(codeface_conf, project_conf)
    project_resdir = pathjoin(resdir, conf["project"], "techsmell")

    #-----------------------------
    # folder setup
    #-----------------------------
    if not pathexists(project_resdir):
        try:
            makedirs(project_resdir)
        except os_error as e:
            log.exception("Could not create output dir {0}: {1}".
                          format(project_resdir, e.strerror))
            raise

    log.info("=> Performing tech smell analysis")
    #-----------------------------
    # tech smell csv
    #-----------------------------
    doTechSmellAnalysis(conf, project_resdir, gitdir, tsadir)

    widgets = ['Pass 2/2: ', Percentage(), ' ', Bar()]
    pbar = ProgressBar(widgets=widgets).start()

    exe = abspath(resource_filename(__name__, "R/techsmell.r"))
    cwd, _ = pathsplit(exe)
    cmd = [exe]
    if logfile:
        cmd.extend(("--logfile", "{}.R.techsmell".format(logfile)))
    cmd.extend(("--loglevel", loglevel))
    cmd.extend(("-c", codeface_conf))
    cmd.extend(("-p", project_conf))
    cmd.extend(("-j", str(n_jobs)))
    cmd.append(project_resdir)
    execute_command(cmd, direct_io=True, cwd=cwd)

    pbar.finish()

    log.info("=> Codeface tech smell analysis complete!")
