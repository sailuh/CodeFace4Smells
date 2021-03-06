## This file is part of Codeface. Codeface is free software: you can
## redistribute it and/or modify it under the terms of the GNU General Public
## License as published by the Free Software Foundation, version 2.
##
## This program is distributed in the hope that it will be useful, but WITHOUT
## ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
## FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
## details.
##
## You should have received a copy of the GNU General Public License
## along with this program; if not, write to the Free Software
## Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
##
## Copyright 2013 by Siemens AG, Wolfgang Mauerer <wolfgang.mauerer@siemens.com>
## All Rights Reserved.

## Interface to the ID manager
suppressPackageStartupMessages(library(RCurl))
suppressPackageStartupMessages(library(stringr))
suppressPackageStartupMessages(library(rjson))
source("config.r")

query.cache <- list()

query.user.id.base <- function(host, port, pid, name, email) {
  res <- postForm(str_c("http://", host, ":", port, "/post_user_id"),
                  .params=list(projectID=pid, name=name, email=email),
                  style="post", binary=FALSE, .encoding="utf-8")
  response <- fromJSON(rawToChar(res))
  if (!is.null(response$error)) {
    logwarn(response$error)
    return(NA)
  }
  id <- response$id
  return(id)
}

query.user.id.cached <- function(host, port, pid, name, email) {
  uid = paste(pid, name, email, sep="\t")
  if (with(query.cache, exists(uid))) {
    return(getElement(query.cache, uid))
  }
  logdebug(paste("Missed cache for ", uid, "\n"), logger="id_manager")
  id <- query.user.id.base(host, port, pid, name, email)
  query.cache[uid] <<- id
  return(id)
}

query.user.id <- function(conf, name, email) {
  return(query.user.id.cached(conf$idServiceHostname, conf$idServicePort,
                              conf$pid, name, email))
}

query.decompose.user.id.base <- function(host, port, pid, name.str) {
  res <- postForm(str_c("http://", host, ":", port, "/post_decompose_user_id"),
                  .params=list(projectID=pid, namestr=name.str),
                  style="post", binary=FALSE, .encoding="utf-8")
  response <- fromJSON(rawToChar(res))
  if (!is.null(response$error)) {
    logwarn(response$error)
    return(NA)
  }
  id <- response$id
  return(id)
}

query.decompose.user.id.cached <- function(host, port, pid, name.str) {
  uid = paste(pid, name.str, sep="\t")
  if (with(query.cache, exists(uid))) {
    return(getElement(query.cache, uid))
  }
  logdebug(paste("Missed cache for ", uid, "\n"), logger="id_manager")
  id <- query.decompose.user.id.base(host, port, pid, name.str)
  query.cache[uid] <<- id
  return(id)
}

query.decompose.user.id <- function(conf, name.str) {
    return(query.decompose.user.id.cached(conf$idServiceHostname,
                                          conf$idServicePort,
                                          conf$pid, name.str))
}
