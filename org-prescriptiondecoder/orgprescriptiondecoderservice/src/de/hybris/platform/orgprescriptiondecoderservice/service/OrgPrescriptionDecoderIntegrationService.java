/*
 * Copyright (c) 2025 SAP SE or an SAP affiliate company. All rights reserved.
 */
package de.hybris.platform.orgprescriptiondecoderservice.service;

import de.hybris.platform.orgprescriptiondecoderservice.data.OrgPrescriptionDecoderRequestData;

import java.util.List;


/**
 *
 */
public interface OrgPrescriptionDecoderIntegrationService
{

	public String getDecodedMarkDownData(final OrgPrescriptionDecoderRequestData orgPrescriptionDecoderRequestData);

	public List<String> getMedicinesList(final String ocrText);

	public List<String> getDecodedMedicineList(final OrgPrescriptionDecoderRequestData orgPrescriptionDecoderRequestData);
}
