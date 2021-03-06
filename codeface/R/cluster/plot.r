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
## Copyright 2010, 2011 by Wolfgang Mauerer <wm@linux-kernel.net>
## Copyright 2012, 2013, Siemens AG, Wolfgang Mauerer <wolfgang.mauerer@siemens.com>
## All Rights Reserved.

## Some utility functions for plottin

normalise.commit.dat <- function(dat, subset) {
  dat.subset <- dat[subset]

  ## The size of a diff and the number of changed files can be 0, which
  ## is obviously problematic for the logarithm. Replace these cases
  ## with NA
  dat.subset$LogChangedFiles <- log(dat.subset$ChangedFiles)
  dat.subset$LogDiffSize <- log(dat.subset$DiffSize)
  dat.subset$LogDiffSize[dat.subset$LogDiffSize==-Inf]=0
  dat.subset$LogChangedFiles[dat.subset$LogChangedFiles==-Inf]=0
  dat.subset$LogCmtMsgBytes <- log(dat.subset$CmtMsgBytes)
  dat.subset$LogCmtMsgBytes[dat.subset$LogCmtMsgBytes==-Inf]=0 #NA
  dat.subset$inRC <- as.factor(dat.subset$inRC)

  ## Remove extreme outliers in the non-logged version
  dat.subset$DiffSize <- remove.outliers(dat.subset$DiffSize)
  dat.subset$ChangedFiles <- remove.outliers(dat.subset$ChangedFiles)

  return(dat.subset)
}

## Remove outliers (statistically dubious, but in this case, we won't loose
## much information)
remove.outliers <- function(values) {
  top <- quantile(values, probs=0.995)[1]
  values[values > top] <- NA

  return(values)
}

## We use a custom scatterplot matrix function because the data
## ranges may vary considerably -- this case is not accounted for
## by the standard functions
plot.splom <- function(plot.types, dat) {
  dat.base <- dat[c(plot.types, "inRC")]
  plot.comb <- expand.grid(1:length(plot.types), 1:length(plot.types))
  plots <- vector("list", dim(plot.comb)[1])

  for (i in 1:dim(plot.comb)[1]) {
    comb <- plot.comb[i,]
    .dat <- data.frame(x=dat.base[,comb$Var1], y=dat.base[,comb$Var2],
                       inRC=dat.base$inRC)
    if (comb$Var1 == comb$Var2) {
      ## Create a histogram instead of comparing a covariate with itself
      plots[[i]] <- ggplot(.dat, aes(x=x)) + geom_density() +
        xlab(colnames(dat.base)[comb$Var1]) +
          ylab("")
    } else {
      ## TODO: Shrink the point size depending on the number
      ## of available data points
      plots[[i]] <- ggplot(.dat, aes(x=x, y=y, colour=inRC)) +
        geom_point(size=0.8, position="jitter") +
        xlab(colnames(dat.base)[comb$Var1]) +
        ylab(colnames(dat.base)[comb$Var2]) + geom_smooth(method="lm") +
        theme(legend.position="none") +
        scale_colour_manual(values=c("black", "red"))
    }
  }

  return(plots)
}
