/*
 * Copyright (c) 2021 SAP SE or an SAP affiliate company. All rights reserved.
 */
package de.hybris.platform.orgprescriptiondecoderservice.setup;

import static de.hybris.platform.orgprescriptiondecoderservice.constants.OrgprescriptiondecoderserviceConstants.PLATFORM_LOGO_CODE;

import de.hybris.platform.core.initialization.SystemSetup;

import java.io.InputStream;

import de.hybris.platform.orgprescriptiondecoderservice.constants.OrgprescriptiondecoderserviceConstants;
import de.hybris.platform.orgprescriptiondecoderservice.service.OrgprescriptiondecoderserviceService;


@SystemSetup(extension = OrgprescriptiondecoderserviceConstants.EXTENSIONNAME)
public class OrgprescriptiondecoderserviceSystemSetup
{
	private final OrgprescriptiondecoderserviceService orgprescriptiondecoderserviceService;

	public OrgprescriptiondecoderserviceSystemSetup(final OrgprescriptiondecoderserviceService orgprescriptiondecoderserviceService)
	{
		this.orgprescriptiondecoderserviceService = orgprescriptiondecoderserviceService;
	}

	@SystemSetup(process = SystemSetup.Process.ALL, type = SystemSetup.Type.ESSENTIAL)
	public void createEssentialData()
	{
		orgprescriptiondecoderserviceService.createLogo(PLATFORM_LOGO_CODE);
	}

	private InputStream getImageStream()
	{
		return OrgprescriptiondecoderserviceSystemSetup.class.getResourceAsStream("/orgprescriptiondecoderservice/sap-hybris-platform.png");
	}
}
