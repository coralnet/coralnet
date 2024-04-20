from django.db.utils import IntegrityError
from django_migration_testcase import MigrationTest
from guardian.shortcuts import get_users_with_perms

from lib.tests.utils import sample_image_as_file


class MigrateSourceFromImagesAppTest(MigrationTest):

    before = [
        ('contenttypes', '0002_remove_content_type_name'),
        ('guardian', '0002_generic_permissions_index'),

        ('annotations', '0023_populate_annoinfo_status'),
        ('calcification', '0002_use_new_jsonfield'),
        ('jobs', '0015_unique_incomplete_jobs_and_more'),
        ('vision_backend', '0021_features_populate_has_rowcols'),

        ('images', '0001_squashed_0033_remove_image_annotation_progress'),
    ]
    after = [
        ('images', '0040_delete_source'),
    ]

    def test_source_memberships(self):
        """
        Save some source memberships before migration, then see if they gets
        correctly migrated.
        """
        User = self.get_model_before('auth.User')
        Source = self.get_model_before('images.Source')
        Permission = self.get_model_before('auth.Permission')
        UserObjectPermission = self.get_model_before(
            'guardian.UserObjectPermission')
        ContentType = self.get_model_before('contenttypes.ContentType')

        user_admin = User(username='user_admin')
        user_admin.save()
        user_editor = User(username='user_editor')
        user_editor.save()
        user_viewer = User(username='user_viewer')
        user_viewer.save()
        user = User(username='user')
        user.save()
        source_1 = Source(name="Source 1")
        source_1.save()
        source_2 = Source(name="Source 2")
        source_2.save()

        # Add source memberships.
        # We can't use the guardian shortcut assign_perm() here, because
        # we can only work with models gotten through get_model_before().
        content_type = ContentType.objects.get(
            app_label='images', model='source')
        for perm_codename, perm_user, perm_source in [
            ('source_admin', user_admin, source_1),
            ('source_admin', user_admin, source_2),
            ('source_edit', user_editor, source_1),
            ('source_view', user_viewer, source_2),
        ]:
            permission = Permission.objects.get(
                codename=perm_codename, content_type=content_type)
            UserObjectPermission(
                content_type=content_type,
                permission=permission,
                user_id=perm_user.pk,
                object_pk=perm_source.pk,
            ).save()

        self.run_migration()

        Source = self.get_model_after('sources.Source')

        source_1 = Source.objects.get(name="Source 1")
        source_2 = Source.objects.get(name="Source 2")

        source_1_usernames = get_users_with_perms(source_1).order_by(
            'username').values_list('username', flat=True)
        self.assertListEqual(
            list(source_1_usernames), ['user_admin', 'user_editor'],
            msg="Source 1 should still have memberships intact")

        source_2_usernames = get_users_with_perms(source_2).order_by(
            'username').values_list('username', flat=True)
        self.assertListEqual(
            list(source_2_usernames), ['user_admin', 'user_viewer'],
            msg="Source 2 should still have memberships intact")

    def test_migrate_foreign_key_data(self):
        """
        Save source-FK data before migration, then see if they get
        correctly migrated.
        """
        User = self.get_model_before('auth.User')
        Annotation = self.get_model_before('annotations.Annotation')
        AnnotationToolAccess = self.get_model_before(
            'annotations.AnnotationToolAccess')
        CalcifyRateTable = self.get_model_before(
            'calcification.CalcifyRateTable')
        Image = self.get_model_before('images.Image')
        Metadata = self.get_model_before('images.Metadata')
        Point = self.get_model_before('images.Point')
        Source = self.get_model_before('images.Source')
        SourceInvite = self.get_model_before('images.SourceInvite')
        Job = self.get_model_before('jobs.Job')
        Label = self.get_model_before('labels.Label')
        LabelGroup = self.get_model_before('labels.LabelGroup')
        Classifier = self.get_model_before('vision_backend.Classifier')
        Score = self.get_model_before('vision_backend.Score')

        user = User()
        user.save()
        source_1 = Source(name="Source 1")
        source_1.save()
        source_2 = Source(name="Source 2")
        source_2.save()

        # Make every possible source FK

        metadata = Metadata()
        metadata.save()
        image = Image(
            source=source_1,
            original_file=sample_image_as_file('a.png'),
            metadata=metadata,
        )
        image.save()

        label_group = LabelGroup()
        label_group.save()
        label = Label(group=label_group)
        label.save()
        point = Point(
            image=image,
            row=1,
            column=1,
            point_number=1,
        )
        point.save()
        annotation = Annotation(
            source=source_2,
            point=point,
            image=image,
            label=label,
        )
        annotation.save()

        annotation_tool_access = AnnotationToolAccess(
            source=source_1,
            image=image,
        )
        annotation_tool_access.save()

        calcify_rate_table = CalcifyRateTable(
            source=source_2,
            rates_json={},
        )
        calcify_rate_table.save()

        invite = SourceInvite(
            source=source_1,
            sender=user,
            recipient=user,
        )
        invite.save()

        job = Job(source=source_2)
        job.save()

        classifier = Classifier(source=source_1)
        classifier.save()

        score = Score(
            source=source_2,
            label=label,
            point=point,
            image=image,
        )
        score.save()

        self.run_migration()

        Image = self.get_model_after('images.Image')
        Annotation = self.get_model_after('annotations.Annotation')
        AnnotationToolAccess = self.get_model_after(
            'annotations.AnnotationToolAccess')
        CalcifyRateTable = self.get_model_after(
            'calcification.CalcifyRateTable')
        SourceInvite = self.get_model_after('sources.SourceInvite')
        Job = self.get_model_after('jobs.Job')
        Classifier = self.get_model_after('vision_backend.Classifier')
        Score = self.get_model_after('vision_backend.Score')

        # Just not getting any constraint errors up to this point is mainly
        # what we're interested in. But to be sure, check the migrated FKs.

        self.assertEqual(
            Image.objects.get(pk=image.pk).source_id,
            source_1.pk)
        self.assertEqual(
            Annotation.objects.get(pk=annotation.pk).source_id,
            source_2.pk)
        self.assertEqual(
            AnnotationToolAccess.objects.get(
                pk=annotation_tool_access.pk).source_id,
            source_1.pk)
        self.assertEqual(
            CalcifyRateTable.objects.get(pk=calcify_rate_table.pk).source_id,
            source_2.pk)
        self.assertEqual(
            SourceInvite.objects.get(pk=invite.pk).source_id,
            source_1.pk)
        self.assertEqual(
            Job.objects.get(pk=job.pk).source_id,
            source_2.pk)
        self.assertEqual(
            Classifier.objects.get(pk=classifier.pk).source_id,
            source_1.pk)
        self.assertEqual(
            Score.objects.get(pk=score.pk).source_id,
            source_2.pk)

    def assert_save_raises_constraint_based_error(self, model_instance):
        with self.assertRaises(IntegrityError) as cm:
            model_instance.save()
        self.assertIn("violates foreign key constraint", str(cm.exception))

    def test_foreign_keys_db_constraints_reapplied(self):
        """
        After the migration, try to save some bogus FKs to test that the
        db_constraint flags have been restored.
        """
        self.run_migration()
        User = self.get_model_after('auth.User')
        Annotation = self.get_model_after('annotations.Annotation')
        AnnotationToolAccess = self.get_model_after(
            'annotations.AnnotationToolAccess')
        CalcifyRateTable = self.get_model_after(
            'calcification.CalcifyRateTable')
        Image = self.get_model_after('images.Image')
        Metadata = self.get_model_after('images.Metadata')
        Point = self.get_model_after('images.Point')
        Source = self.get_model_after('sources.Source')
        SourceInvite = self.get_model_after('sources.SourceInvite')
        Job = self.get_model_after('jobs.Job')
        Label = self.get_model_after('labels.Label')
        LabelGroup = self.get_model_after('labels.LabelGroup')
        Classifier = self.get_model_after('vision_backend.Classifier')
        Score = self.get_model_after('vision_backend.Score')

        user = User()
        user.save()
        source = Source()
        source.save()
        # Pretty unlikely that we'll hit this high of an ID (max AutoField
        # value) in a test environment.
        nonexistent_source_id = 2**31 - 1
        # And let's sanity-check either way.
        self.assertNotEqual(source.pk, nonexistent_source_id)

        # Try to every possible source FK

        metadata = Metadata()
        metadata.save()
        image = Image(
            source_id=nonexistent_source_id,
            original_file=sample_image_as_file('a.png'),
            metadata=metadata,
        )
        self.assert_save_raises_constraint_based_error(image)

        # We need to actually save an Image to properly test Annotation.
        image = Image(
            source=source,
            original_file=sample_image_as_file('a.png'),
            metadata=metadata,
        )
        image.save()

        label_group = LabelGroup()
        label_group.save()
        label = Label(group=label_group)
        label.save()
        point = Point(
            image=image,
            row=1,
            column=1,
            point_number=1,
        )
        point.save()
        annotation = Annotation(
            source_id=nonexistent_source_id,
            point=point,
            image=image,
            label=label,
        )
        self.assert_save_raises_constraint_based_error(annotation)

        annotation_tool_access = AnnotationToolAccess(
            source_id=nonexistent_source_id,
            image=image,
        )
        self.assert_save_raises_constraint_based_error(annotation_tool_access)

        calcify_rate_table = CalcifyRateTable(
            source_id=nonexistent_source_id,
            rates_json={},
        )
        self.assert_save_raises_constraint_based_error(calcify_rate_table)

        invite = SourceInvite(
            source_id=nonexistent_source_id,
            sender=user,
            recipient=user,
        )
        self.assert_save_raises_constraint_based_error(invite)

        job = Job(source_id=nonexistent_source_id)
        self.assert_save_raises_constraint_based_error(job)

        classifier = Classifier(source_id=nonexistent_source_id)
        self.assert_save_raises_constraint_based_error(classifier)

        score = Score(
            source_id=nonexistent_source_id,
            label=label,
            point=point,
            image=image,
        )
        self.assert_save_raises_constraint_based_error(score)
