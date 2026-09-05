// Painted contact shadow under the signer.
//
// The rig's key light casts a real shadow, but the avatar stands on a backdrop rather than a floor,
// so there is nothing for that shadow to land on. This blob supplies the grounding instead: a soft
// ellipse multiplied into the backdrop so the figure does not read as floating.
Shader "Signora/SoftShadowBlob"
{
    Properties
    {
        _Color ("Color", Color) = (0, 0, 0, 0.45)
        _Radius ("Radius", Range(0, 0.5)) = 0.08
        _Softness ("Softness", Range(0.001, 0.6)) = 0.34
        _Power ("Falloff Power", Range(0.5, 6)) = 2.2
    }

    SubShader
    {
        Tags { "RenderType" = "Transparent" "RenderPipeline" = "UniversalPipeline" "Queue" = "Transparent" }
        LOD 100

        Pass
        {
            Name "ShadowBlob"
            Tags { "LightMode" = "UniversalForward" }
            Blend SrcAlpha OneMinusSrcAlpha
            Cull Off
            ZWrite Off
            ZTest LEqual

            HLSLPROGRAM
            #pragma vertex Vert
            #pragma fragment Frag

            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"

            struct Attributes
            {
                float4 positionOS : POSITION;
                float2 uv         : TEXCOORD0;
                UNITY_VERTEX_INPUT_INSTANCE_ID
            };

            struct Varyings
            {
                float4 positionCS : SV_POSITION;
                float2 uv         : TEXCOORD0;
                UNITY_VERTEX_OUTPUT_STEREO
            };

            CBUFFER_START(UnityPerMaterial)
                half4 _Color;
                float _Radius;
                float _Softness;
                float _Power;
            CBUFFER_END

            Varyings Vert(Attributes IN)
            {
                Varyings OUT = (Varyings)0;
                UNITY_SETUP_INSTANCE_ID(IN);
                UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(OUT);
                OUT.positionCS = TransformObjectToHClip(IN.positionOS.xyz);
                OUT.uv = IN.uv;
                return OUT;
            }

            half4 Frag(Varyings IN) : SV_Target
            {
                float r = length(IN.uv - 0.5);
                float mask = 1.0 - smoothstep(_Radius, _Radius + _Softness, r);
                return half4(_Color.rgb, _Color.a * pow(saturate(mask), _Power));
            }
            ENDHLSL
        }
    }

    Fallback "Universal Render Pipeline/Unlit"
}
