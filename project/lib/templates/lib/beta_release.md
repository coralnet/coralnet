# CoralNet Beta Release: Nov 2016

The CoralNet Beta release is a major software and systems upgrade involving most parts of the site. Below is a summary of the main changes.


## Hardware

CoralNet Beta is hosted at Amazon Web Services (AWS). The means that the web-server, database and the image data now lives at professionally managed data-centers, which guarantees virtually constant uptime and strong backup and data redundancy plans.


## Upload and image file names

All image names in a source must now be unique. This is enforced during upload.

We have re-named all images with identical file-names as xxx__dupe-name-01.jpg, xxx__dupe-name-02.jpg, etc. To find and rename these images the way you want, you can go to the Metadata page, use the "Image name contains" search option, and edit the names to your liking.

Image upload, metadata upload, and archived-annotation upload are now three separate steps. CSV file reading is now more flexible; columns can be in any order, and you can omit columns you don't need.


## Auxiliary metadata fields

Location keys have been renamed to auxiliary metadata fields, and there are now always 5 per source.


## Browse

This has been split up into three separate pages, now reachable with the menu buttons Images, Metadata, and Patches.

Filtering is now allowed on any metadata field, not just on the auxiliary metadata-fields.

Image delete and export functions now reside in Browse Images.


## Annotation work-flow

From Browse Images, if you do an image search and then use the "Enter Annotation Tool" action at the bottom of the page, the annotation tool's Previous and Next buttons will scroll through only the images you searched for.


## Computer vision back-end

The computer vision back-end system is rebuilt from scratch. The new system relies on deep convolutional neural networks and is deployed using a scalable cluster hosted at AWS. We have also modified some of the processing and interface logic.

Major changes as a result of the redesign are:

- Orders of magnitude faster processing.

- Dedicated back-end analytics page.

- We have changed back to letting users directly specify the confidence threshold instead of the previous "alleviate" threshold.

- The back-end does no longer run each 24 hours, but a job will be triggered immediately after upload. You can therefore expect an uploaded image to be automatically annotated within minutes of upload.

- According to our experiments we further expect the actual *accuracy* to increase significantly.

Note that we have to re-process ALL IMAGES already uploaded on the site. There will be delays initially because of this.


## Labelset logic

We have made several update to the way labels are handled in CoralNet.

- While the labels themselves remain global, we now allow users to set the label-codes on a source level. This allows a uniform set of codes for everyone while still sharing the labels themselves.

- Labels can now be edited if (and only if) (1) no-one else is using the label and (2) the labelset-committee hasn't already verified it \[see below].

- Source label-sets, including the custom label-codes, can be exported into a simple CSV file format and then re-uploaded to another source.

- We have added a popularity field to encourage emergence of labels used and shared by multiple groups. This is to encourage and facilitate meta-analysis across projects.


## Labelset committee

We have created a special group of users called the labelset committee (LSC). The long-term goal of the LSC to encourage and shepherd the community towards a unified set of global labels.

In practice, the LSC will be responsible for maintaining the global labelset with emphasis on:

- Ensuring consistent label names.

- Ensuring that label descriptions are sufficient.

- Updating species and genera as the scientific literature evolves.

The labelset committee will therefore have authority to edit any label on the site. Labels inspected, and maintained by the LSC will be designated as "verified", and the user interface will encourage future label-sets to include as many verified labels as possible. As the LSC goes through the existing set of labels and finds duplicates, the most commonly used labels will be chosen as verified.

NOTE: no labels will be deleted from the site, and users can still create any labels they want.